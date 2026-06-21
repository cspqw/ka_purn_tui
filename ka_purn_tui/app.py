# ── Textual App 主入口 ─────────────────────────────────
"""KAPurnTUI App：分屏布局、模式切换、窗口缩放适配、命令路由、聊天 worker。

布局：顶栏 + 左右分栏（左聊天 / 右实时追踪面板）+ 底部输入栏。
模式切换时 recompose 右侧面板；窗口缩放时按宽度阈值调整比例/折叠右侧。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Static, Tree

from .api.client import DeepSeekClient
from .config import (
    AVAILABLE_MODELS,
    DEFAULT_PRESETS,
    SESSIONS_FILE,
    apply_special_prompt,
    estimate_tokens,
    get_project_sessions_path,
    load_config,
    save_config,
)
from .modes.base import Mode
from .modes.chat import ChatMode
from .modes.novel import NovelMode
from .state.novel_state import NovelState
from .state.project_state import ProjectStateStore
from .state.session_store import Session, SessionStore
from .tools.executor import ToolExecutor, build_novel_registry
from .widgets.chat_view import ChatView
from .widgets.input_bar import InputBar
from .widgets.sessions_screen import SessionsScreen

# 常驻记忆维护工具集合：执行后需刷新 system prompt 以注入最新记忆
_MEMORY_TOOLS = {
    "update_character_card",
    "update_world_setting",
    "update_outline",
    "update_style_guide",
}


def _strip_quotes(s: str) -> str:
    """去除首尾匹配的引号（双引号或单引号），用于处理终端拖入的带引号路径。"""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _extract_partial_string(json_str: str, field: str) -> str | None:
    """从可能不完整的 JSON 字符串中提取 field 字段的已接收字符串值。

    用于流式预览：tool_call arguments 是逐步累积的 JSON 片段，
    此函数启发式提取某个字符串字段的已解码部分（处理 \\n \\" 等转义）。
    返回 None 表示字段尚未开始，"" 表示字段已开始但暂无内容。

    兼容 JSON 键值间的空格（如 "path": "ch01.md" 和 "path":"ch01.md"）。
    """
    import re

    # 匹配: "field" : "  （允许冒号前后有空格）
    pattern = re.compile(r'"' + re.escape(field) + r'"\s*:\s*"')
    m = pattern.search(json_str)
    if not m:
        return None
    i = m.end()  # 跳过 "field" : "  指向值字符串的第一个字符
    n = len(json_str)
    result: list[str] = []
    while i < n:
        c = json_str[i]
        if c == "\\":
            if i + 1 < n:
                nxt = json_str[i + 1]
                mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
                if nxt in mapping:
                    result.append(mapping[nxt])
                    i += 2
                    continue
                if nxt == "u" and i + 5 < n:
                    try:
                        result.append(chr(int(json_str[i + 2 : i + 6], 16)))
                        i += 6
                        continue
                    except ValueError:
                        pass
            i += 1
        elif c == '"':
            break  # 字符串结束
        else:
            result.append(c)
            i += 1
    return "".join(result)


class KAPurnTUI(App):
    """K.A-purn-tui 主应用。"""

    CSS = """
    #top-bar {
        dock: top;
        height: 1;
        background: $primary 30%;
        color: $text;
        padding: 0 1;
    }
    #main-area {
        height: 1fr;
    }
    /* 默认（chat 模式 / 无右侧面板）：左侧全宽，右侧隐藏 */
    #left-pane {
        width: 1fr;
    }
    #right-pane {
        width: 1fr;
        display: none;
    }
    /* 有右侧面板时（novel 模式）才分栏 */
    .has-right #right-pane {
        display: block;
    }
    /* 宽窗口：2:1 */
    .has-right.wide #left-pane {
        width: 2fr;
    }
    .has-right.wide #right-pane {
        width: 1fr;
    }
    /* 中等窗口：1:1 */
    .has-right.medium #left-pane {
        width: 1fr;
    }
    .has-right.medium #right-pane {
        width: 1fr;
    }
    /* 窄窗口：即使有面板也隐藏右侧 */
    .has-right.narrow #right-pane {
        display: none;
    }
    .has-right.narrow #left-pane {
        width: 1fr;
    }
    /* 手动隐藏右侧 */
    .right-hidden #right-pane {
        display: none;
    }
    .right-hidden #left-pane {
        width: 1fr;
    }
    InputBar {
        dock: bottom;
    }
    """

    BINDINGS = [
        Binding("ctrl+r", "toggle_right", "右侧面板", show=True),
        Binding("ctrl+c", "stop_or_quit", "停止推理/退出", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config: dict[str, Any] = load_config()
        self.client = DeepSeekClient(self.config)
        self.chat_mode = ChatMode()
        # 从配置读取小说模式系统提示词
        novel_prompt = self.config.get("novel", {}).get("system_prompt")
        self.novel_mode = NovelMode(system_prompt=novel_prompt)
        # 恢复预设
        self.chat_mode.presets = self.config.get("presets", DEFAULT_PRESETS.copy())
        self.chat_mode.current_preset = self.config.get("current_preset", "default")
        self.modes: dict[str, Mode] = {"chat": self.chat_mode, "novel": self.novel_mode}
        self.current_mode_name: str = self.config.get("current_mode", "chat")
        self.novel_state = NovelState()
        self.tool_executor = ToolExecutor(build_novel_registry(), self.novel_state)
        self.right_visible: bool = True
        self._layout_class = "wide"
        self._busy = False
        # 从配置读取 UI / agent 运行时参数
        ui_cfg = self.config.get("ui", {})
        self.width_narrow: int = int(ui_cfg.get("width_narrow", 100))
        self.width_wide: int = int(ui_cfg.get("width_wide", 160))
        self.width_hysteresis: int = int(ui_cfg.get("width_hysteresis", 5))
        self.flush_threshold: int = int(ui_cfg.get("flush_threshold", 80))
        agent_cfg = self.config.get("agent", {})
        self.max_agent_rounds: int = int(agent_cfg.get("max_rounds", 12))
        # 上下文管理配置
        ctx_cfg = self.config.get("context", {})
        self.auto_summarize_on_chapter_done: bool = bool(
            ctx_cfg.get("auto_summarize_on_chapter_done", True)
        )
        self.chapter_summary_max_chars: int = int(ctx_cfg.get("chapter_summary_max_chars", 400))
        # 水位告警回调
        self.client.on_context_warning = self._on_context_warning
        # 待摘要的章节队列（mark_chapter_done 后入队，agent 结束后处理）
        self._pending_chapter_summaries: list[int] = []
        # ── 计划确认跟踪 ──
        self._pending_plan_file: str | None = None  # 待用户确认的计划文件路径
        # ── 多会话管理 ──
        self.session_store = SessionStore(SESSIONS_FILE)
        self.current_session: Session = self._init_or_restore_session()

    def _init_or_restore_session(self) -> Session:
        """启动时恢复当前会话，或迁移旧 history / 新建会话。"""
        sid = self.config.get("current_session_id", "")
        session = self.session_store.get(sid) if sid else None
        if session is not None:
            # 恢复已保存的会话：载入消息历史与模式
            self.client.load_messages(session.messages)
            if session.mode in self.modes:
                self.current_mode_name = session.mode
            # 恢复会话级状态（常驻记忆 + 创作进度）
            if session.mode == "novel":
                self.novel_state.restore_session_state(
                    {
                        "novel_memory": session.novel_memory,
                        "novel_progress": session.novel_progress,
                    }
                )
            return session
        # 迁移：若旧 config.json 有 history，将其作为首个会话
        old_history = self.config.get("history", [])
        if old_history:
            mode = self.current_mode_name
            session = self.session_store.create("迁移的历史会话", mode)
            session.messages = list(old_history)
            session.touch()
            self.session_store.save()
            self.client.load_messages(session.messages)
            self.config["current_session_id"] = session.id
            save_config(self.config)
            return session
        # 全新启动：创建空会话
        session = self.session_store.create("新会话", self.current_mode_name)
        self.config["current_session_id"] = session.id
        save_config(self.config)
        return session

    # ── 布局 ──
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(self._render_top_bar(), id="top-bar")
        with Horizontal(id="main-area"):
            yield ChatView(id="left-pane", flush_threshold=self.flush_threshold)
            with Vertical(id="right-pane"):
                pass  # 右侧面板按模式动态挂载
        yield InputBar()

    def on_mount(self) -> None:
        self.title = "K.A-purn-tui"
        self.sub_title = self.current_mode.display_name
        self._apply_layout()
        self._compose_right_pane()
        self._init_system_prompt()
        # 从 config 恢复输入历史到 InputBar
        input_bar = self.query_one(InputBar)
        input_bar.input.set_history(self.config.get("input_history", []))
        # 注入提交回调（Ctrl+Enter 触发）
        input_bar.input.set_submit_callback(self._submit_input)
        # 同步初始模式（用于命令补全过滤，避免启动在 novel 模式时仍按 chat 过滤）
        input_bar.set_mode(self.current_mode_name)
        input_bar.focus_input()
        # 欢迎信息
        cv = self.query_one(ChatView)
        cv.write_info(f"K.A-purn-tui 已就绪 · 当前模式: {self.current_mode.display_name}")
        cv.write_info(self.current_mode.get_help())
        cv.write_separator()

    @property
    def current_mode(self) -> Mode:
        return self.modes[self.current_mode_name]

    def _render_top_bar(self) -> str:
        mode = self.current_mode
        think = "开" if self.client.thinking_enabled else "关"
        effort = self.client.reasoning_effort or "-"
        proj = f" | 项目: {self.novel_state.project_name}" if self.novel_state.project_name else ""
        # 当前活跃待办（黄色指针）
        active_todo = ""
        if self.current_mode_name == "novel":
            for t in self.novel_state.todos:
                if t.status == "active" and not t.done:
                    text = t.text[:20] + (".." if len(t.text) > 20 else "")
                    active_todo = f" | [yellow]▸ {text}[/yellow]"
                    break
        narrow_hint = " | [窗口过窄，右侧已折叠 Ctrl+R]" if self._layout_class == "narrow" else ""
        sess = self.current_session.name if self.current_session else "无会话"
        # 上下文占用进度条（按水位着色：绿<60% / 黄60-80% / 红80-90% / 亮红≥90%）
        tokens = estimate_tokens(self.client.messages)
        tokens += self.client._tool_tokens
        max_ctx = self.client.context_max_tokens
        pct = (tokens / max_ctx * 100) if max_ctx else 0
        bar_len = 10
        filled = min(bar_len, int(round(bar_len * pct / 100)))
        bar = "█" * filled + "░" * (bar_len - filled)
        if pct >= 90:
            color = "bright_red"
        elif pct >= 80:
            color = "red"
        elif pct >= 60:
            color = "yellow"
        else:
            color = "green"
        ctx = f" | 上下文: [{color}]{bar}[/{color}] {pct:.2f}%"
        # 自定义进度条（由模型 set_progress 驱动）
        progress_bar = ""
        if self.current_mode_name == "novel":
            pg = self.novel_state
            if pg.progress_total > 0:
                pg_pct = pg.progress_current / pg.progress_total * 100
                pg_len = 12
                pg_filled = min(pg_len, int(round(pg_len * pg.progress_current / pg.progress_total)))
                pg_bar = "▓" * pg_filled + "░" * (pg_len - pg_filled)
                label = pg.progress_label + "  " if pg.progress_label else ""
                progress_bar = f" | {label}{pg.progress_current}/{pg.progress_total} {pg_pct:.0f}% [{pg_bar}]"
        return (
            f"[{mode.display_name}] {self.client.model} | 思考:{think}/{effort}"
            f" | 会话: {sess}{active_todo}{proj}{progress_bar}{ctx}{narrow_hint}"
        )

    def _render_system_prompt(self) -> str:
        """构造完整 system prompt：模式提示词 + 常驻记忆块，再前置特殊提示词。"""
        base = self.current_mode.get_system_prompt()
        # 注入常驻记忆（仅 novel 模式）
        if self.current_mode_name == "novel":
            memory_block = self.novel_state.render_memory_block()
            if memory_block:
                base = base + "\n\n" + memory_block
        return apply_special_prompt(self.config, base)

    def _init_system_prompt(self) -> None:
        self.client.set_system(self._render_system_prompt())

    def _on_context_warning(self, level: str, ratio: float) -> None:
        """上下文水位告警（由 client 回调，在 worker 线程中触发）。"""
        try:
            cv = self.query_one(ChatView)
            pct = ratio * 100
            if level == "警戒":
                cv.write_warn(f"[上下文警戒] 占用 {pct:.1f}%，已自动精简旧 tool result")
            elif level == "压缩":
                cv.write_warn(f"[上下文压缩] 占用 {pct:.1f}%，需要生成早期对话摘要")
            elif level == "紧急":
                cv.write_error(f"[上下文紧急] 占用 {pct:.1f}%，已强制截断早期对话！")
        except Exception:  # noqa: BLE001
            pass

    # ── 右侧面板动态挂载 ──
    def _compose_right_pane(self) -> None:
        right = self.query_one("#right-pane")
        # 移除旧面板
        for child in list(right.children):
            child.remove()
        panels = self.current_mode.get_right_panels()
        # 有面板才分栏（加 .has-right），否则左侧全宽
        if panels:
            self.add_class("has-right")
            for panel_cls in panels:
                right.mount(panel_cls())
            # 面板内部 compose 异步完成，延迟到下一刷新周期再填充内容
            self.call_after_refresh(self._refresh_right_panels)
        else:
            self.remove_class("has-right")
        self._apply_layout()

    def _refresh_right_panels(self) -> None:
        """刷新所有右侧面板内容。"""
        if self.current_mode_name != "novel":
            return
        right = self.query_one("#right-pane")
        from .panels.base import BaseRightPanel
        from .panels.file_preview_panel import FilePreviewPanel
        from .panels.file_tree_panel import FileTreePanel
        from .panels.side_panels import SidePanels

        for child in right.children:
            if isinstance(child, (BaseRightPanel, FilePreviewPanel, FileTreePanel)):
                child.refresh_state(self.novel_state)
            elif isinstance(child, SidePanels):
                child.refresh_state(self.novel_state)

    # ── 流式文件预览 ──
    def _on_tool_streaming(self, tool_name: str, args_str: str) -> None:
        """tool_call arguments 流式累积时，实时更新文件预览面板。"""
        if self.current_mode_name != "novel":
            return
        # 提取 path 和文本字段
        path = _extract_partial_string(args_str, "path")
        if not path:
            return
        # 模型开始写入文件时，强制抢占预览面板为 model 模式
        if self.novel_state.preview_source != "model" or self.novel_state.preview_file != path:
            self.novel_state.preview_source = "model"
            self.novel_state.preview_file = path
        # 按工具类型提取文本字段
        if tool_name == "append_to_file":
            partial = _extract_partial_string(args_str, "text") or ""
        elif tool_name in ("create_novel_file", "write_file"):
            partial = _extract_partial_string(args_str, "content") or ""
        elif tool_name == "edit_file":
            partial = _extract_partial_string(args_str, "text")
            if partial is None:
                partial = _extract_partial_string(args_str, "replace") or ""
            else:
                partial = partial or ""
        else:
            return
        # 更新 novel_state，作为预览内容的权威来源
        if self.novel_state.project_root is not None:
            if tool_name == "append_to_file":
                try:
                    fp = self.novel_state.project_root / path
                    existing = fp.read_text(encoding="utf-8") if fp.exists() and fp.is_file() else ""
                except Exception:
                    existing = ""
                self.novel_state.preview_content = existing + partial
            else:
                self.novel_state.preview_content = partial
        # 增量写入预览面板——只追加新增内容，不清空重绘
        # 用 _refresh_right_panels 同样的方式（遍历 children + isinstance）找面板，
        # 比 query_one 更可靠，不依赖 CSS 选择器和 Textual 内部刷新时机
        right = self.query_one("#right-pane")
        panel = None
        from .panels.file_preview_panel import FilePreviewPanel

        for child in right.children:
            if isinstance(child, FilePreviewPanel):
                panel = child
                break
        if panel is not None:
            try:
                panel.streaming_update(tool_name, path, partial)
            except Exception as e:
                try:
                    cv = self.query_one(ChatView)
                    cv.write_warn(f"[预览] 流式更新异常: {e}")
                except Exception:
                    pass
        else:
            try:
                cv = self.query_one(ChatView)
                cv.write_warn("[预览] 找不到 FilePreviewPanel")
            except Exception:
                pass

    def _on_tool_streaming_end(self) -> None:
        """tool_call 真正执行前，结束流式预览模式。"""
        pass  # 流式内容已通过 _on_tool_streaming 直接写入了 RichLog

    # ── 文件树点击：打开文件到预览面板 ──
    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """文件树节点选中：打开文件到预览面板。

        - 点击其他文件 → user 模式，显示完整内容（无行数限制）
        - 点击模型正在编辑的文件 → model 模式，恢复实时流式进度
        """
        if self.current_mode_name != "novel":
            return
        rel_path = event.node.data
        if not isinstance(rel_path, str):
            return
        root = self.novel_state.project_root
        if root is None:
            return
        # 点击模型正在编辑的文件 → 切回 model 模式看实时进度
        if rel_path == self.novel_state.current_file:
            self.novel_state.preview_source = "model"
            self.novel_state.preview_file = self.novel_state.current_file
            self.novel_state.preview_content = self.novel_state.current_file_content
        else:
            # 读取文件内容，切到 user 模式
            fp = root / rel_path
            if not fp.exists() or not fp.is_file():
                return
            try:
                content = fp.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                return
            self.novel_state.preview_source = "user"
            self.novel_state.preview_file = rel_path
            self.novel_state.preview_content = content
        self._refresh_right_panels()

    # ── 窗口缩放适配 ──
    def _apply_layout(self) -> None:
        """根据当前尺寸应用布局类。"""
        w = self.size.width if hasattr(self, "size") else 120
        # 滞回：避免边界来回跳
        if self._layout_class == "narrow":
            narrow_thresh = self.width_narrow + self.width_hysteresis
        else:
            narrow_thresh = self.width_narrow
        if self._layout_class == "wide":
            wide_thresh = self.width_wide - self.width_hysteresis
        else:
            wide_thresh = self.width_wide

        if w < narrow_thresh:
            new_class = "narrow"
        elif w > wide_thresh:
            new_class = "wide"
        else:
            new_class = "medium"

        if new_class != self._layout_class:
            self._layout_class = new_class
            self.refresh_top_bar()

    def refresh_top_bar(self) -> None:
        try:
            self.query_one("#top-bar", Static).update(self._render_top_bar())
        except Exception:
            pass

    def on_resize(self, event: Any) -> None:
        self._apply_layout()
        # 重新刷新右侧面板（高度变化后预览面板需重排）
        self._refresh_right_panels()

    # ── 模式切换 ──
    def action_stop_or_quit(self) -> None:
        """Ctrl+C：推理中则停止当前推理，空闲则退出 TUI。"""
        if self._busy:
            # 取消所有 chat worker
            for w in list(self.workers):
                if w.name == "chat":
                    w.cancel()
            self._busy = False
            cv = self.query_one(ChatView)
            cv.write_warn("[已停止] 当前推理已中断（历史已保留）")
            cv.write_separator()
            self._sync_current_session()
            self._persist_history()
        else:
            self._sync_current_session()
            self.exit()

    def action_toggle_right(self) -> None:
        self.right_visible = not self.right_visible
        if self.right_visible:
            self.remove_class("right-hidden")
        else:
            self.add_class("right-hidden")
        self._refresh_right_panels()

    def _switch_mode(self, name: str) -> None:
        if name not in self.modes or name == self.current_mode_name:
            return
        # 先保存当前会话到旧 store（模式名保持旧值）
        self._sync_current_session()
        # 更新模式名，确保 _switch_session_store 使用正确的模式
        self.current_mode_name = name
        # SessionStore 动态切换：chat 用全局，novel 用项目级
        if name == "chat":
            self._switch_session_store(SESSIONS_FILE)
        elif name == "novel" and self.novel_state.project_root is not None:
            self._switch_session_store(get_project_sessions_path(self.novel_state.project_root))
        self.config["current_mode"] = name
        save_config(self.config)
        self.sub_title = self.current_mode.display_name
        self._init_system_prompt()
        self._compose_right_pane()
        # 同步 InputBar 的模式（用于命令补全过滤）
        self.query_one(InputBar).set_mode(name)
        self.refresh_top_bar()
        cv = self.query_one(ChatView)
        cv.write_info(f"已切换到 {self.current_mode.display_name} 模式")

    # ── 输入处理 ──
    def _submit_input(self) -> None:
        """提交输入框内容（由 HistoryInput 的 Ctrl+Enter 触发）。"""
        if self._busy:
            self.query_one(ChatView).write_warn("[忙] 模型正在生成，请稍候...")
            return
        input_bar = self.query_one(InputBar)
        raw = input_bar.input.text
        text = raw.strip()
        # 记录输入历史（无论是否为空都先记录原始值，由 record_history 过滤）
        input_bar.input.record_history(raw)
        self.config["input_history"] = input_bar.input.input_history
        save_config(self.config)
        input_bar.clear()
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
        else:
            # 预删除确认：若模型已将文件移至预删除区域，等待用户确认
            if self.novel_state._pre_delete_items:
                lower = text.strip().lower().rstrip("。！!.,;；")
                if lower in ("确认删除", "确认"):
                    from .tools.file_tools import perform_delete
                    result = perform_delete(self.novel_state)
                    cv = self.query_one(ChatView)
                    cv.write_info(result)
                    self._refresh_right_panels()
                    return
                else:
                    from .tools.file_tools import restore_pre_deleted
                    result = restore_pre_deleted(self.novel_state)
                    cv = self.query_one(ChatView)
                    cv.write_info(result)
                    self._refresh_right_panels()
                    return

            # 计划确认：若上一轮模型创建了计划文件且用户输入是确认用语，自动注入计划全文
            if self._pending_plan_file and self.novel_state.project_root:
                lower = text.strip().lower().rstrip("。！!.,;；")
                if lower in ("确认", "执行", "yes", "ok", "y", "是", "好的", "开始", "同意", "可以", "行", "对"):
                    plan_path = self.novel_state.project_root / self._pending_plan_file
                    if plan_path.exists():
                        try:
                            plan_content = plan_path.read_text(encoding="utf-8")
                            cv = self.query_one(ChatView)
                            cv.write_info(f"[计划] 已载入 {self._pending_plan_file}（{len(plan_content)} 字）")
                            text = f"[计划已确认] 以下是你要执行的计划全文:\n\n{plan_content}\n\n请按计划逐步执行。"
                        except Exception:
                            pass
                self._pending_plan_file = None
            self._start_chat(text)

    # ── 命令路由 ──
    def _handle_command(self, cmd: str) -> None:
        cv = self.query_one(ChatView)
        parts = cmd.split(maxsplit=1)
        action = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if action in ("/quit", "/exit", "/q"):
            self.exit()
        elif action == "/help":
            cv.write_info(self.current_mode.get_help())
        elif action == "/mode":
            self._cmd_mode(arg)
        elif action == "/novel":
            self._cmd_novel(arg)
        elif action == "/chapter":
            self._cmd_chapter(arg)
        elif action == "/follow":
            self._cmd_follow(arg)
        elif action == "/panel":
            self._cmd_panel(arg)
        elif action == "/think":
            self._cmd_think(arg)
        elif action == "/effort":
            self._cmd_effort(arg)
        elif action == "/model":
            self._cmd_model(arg)
        elif action == "/load":
            self._cmd_load(arg)
        elif action == "/system":
            if arg:
                self.client.set_system(apply_special_prompt(self.config, arg))
                cv.write_info("[已设置] system prompt")
            else:
                cv.write_warn("[用法] /system <提示词>")
        elif action == "/special":
            self._cmd_special(arg)
        elif action == "/clear":
            self.client.clear()
            self._init_system_prompt()
            if self.current_session:
                self.current_session.messages = list(self.client.messages)
                self.current_session.touch()
                self.session_store.save()
            save_config(self._persist_config())
            cv.write_info("[已清空] 对话历史已重置")
        elif action == "/info":
            self._cmd_info()
        elif action == "/preset":
            self._cmd_preset(arg)
        elif action == "/new":
            self._cmd_new_session(arg)
        elif action in ("/sessions", "/ls"):
            self._cmd_list_sessions()
        elif action == "/load":
            # 兼容：/load <id> 载入会话；若 arg 是文件路径则走原文件加载逻辑
            if arg and arg in self.session_store.sessions:
                self._cmd_load_session(arg)
            else:
                self._cmd_load(arg)
        elif action == "/rename":
            self._cmd_rename_session(arg)
        elif action == "/delete":
            self._cmd_delete_session(arg)
        elif action == "/plan":
            self._cmd_plan(arg)
        else:
            cv.write_warn(f"[未知命令] {action}，输入 /help 查看帮助")

    def _cmd_mode(self, arg: str) -> None:
        cv = self.query_one(ChatView)
        if not arg:
            cv.write_info(f"当前模式: {self.current_mode.display_name}（可用: chat, novel）")
            return
        if arg.lower() in ("chat", "novel"):
            self._switch_mode(arg.lower())
        else:
            cv.write_warn("[用法] /mode chat 或 /mode novel")

    def _cmd_novel(self, arg: str) -> None:
        cv = self.query_one(ChatView)
        if self.current_mode_name != "novel":
            cv.write_warn("请先 /mode novel 切换到小说模式")
            return
        parts = arg.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        name = parts[1] if len(parts) > 1 else ""
        if sub == "new":
            self._create_novel_project(name)
        elif sub == "open":
            self._open_novel_project(name)
        else:
            cv.write_info("用法:\n  /novel new <名称>  新建项目（文件夹）\n  /novel open <路径>  打开项目")

    def _create_novel_project(self, name: str) -> None:
        cv = self.query_one(ChatView)
        name = _strip_quotes(name)
        if not name:
            cv.write_warn("[用法] /novel new <名称>")
            return
        root = Path(name).resolve()
        if root.exists():
            cv.write_warn(f"[警告] 已存在: {root}")
            return
        try:
            # 先保存当前会话到旧 store（项目名/模式名保持旧值）
            self._sync_current_session()
            root.mkdir(parents=True)
            (root / ".Project").mkdir(exist_ok=True)  # 工程文件目录
            self.novel_state.project_root = root
            self.novel_state.project_name = name
            self.config.setdefault("novel_projects", {})[name] = str(root)
            save_config(self.config)
            # 初始化空的项目状态文件
            ProjectStateStore.save_from_state(self.novel_state)
            # 刷新文件树
            from .tools.file_tools import _refresh_file_tree

            _refresh_file_tree(self.novel_state)
            # 切换到项目级 SessionStore（新建会话）
            self._switch_session_store(get_project_sessions_path(root))
            self.refresh_top_bar()
            cv.write_info(f"[已创建] 小说项目: {root}")
        except Exception as e:  # noqa: BLE001
            cv.write_error(f"创建项目失败: {e}")

    def _open_novel_project(self, path: str) -> None:
        cv = self.query_one(ChatView)
        path = _strip_quotes(path)
        if not path:
            cv.write_warn("[用法] /novel open <路径>")
            return
        root = Path(path).resolve()
        if not root.exists():
            cv.write_error(f"路径不存在: {root}")
            return
        # 统一为文件夹：若打开的是文件，取其父目录
        if root.is_file():
            root = root.parent
        try:
            # 先保存当前会话到旧 store（项目名/模式名保持旧值）
            self._sync_current_session()
            self.novel_state.project_root = root
            self.novel_state.project_name = root.name
            # 加载项目级状态（chapter_count/chapters）
            ProjectStateStore.load_to_state(self.novel_state)
            from .tools.file_tools import _refresh_file_tree

            _refresh_file_tree(self.novel_state)
            # 切换到项目级 SessionStore（新建会话）
            self._switch_session_store(get_project_sessions_path(root))
            self.refresh_top_bar()
            cv.write_info(f"[已打开] {self.novel_state.project_root}")
        except Exception as e:  # noqa: BLE001
            cv.write_error(f"打开项目失败: {e}")

    def _cmd_chapter(self, arg: str) -> None:
        cv = self.query_one(ChatView)
        if not arg.isdigit():
            cv.write_warn("[用法] /chapter <章节序号>")
            return
        n = int(arg)
        if not (1 <= n <= self.novel_state.chapter_count):
            cv.write_warn(f"序号越界（总 {self.novel_state.chapter_count} 章）")
            return
        self.novel_state.current_chapter = n
        self._refresh_right_panels()
        cv.write_info(f"已跳转到第 {n} 章")

    def _cmd_follow(self, arg: str) -> None:
        cv = self.query_one(ChatView)
        if arg.lower() in ("on", "开", "1", "true"):
            self.novel_state.follow = True
            cv.write_info("[跟随] 已开启文件预览自动滚动")
        elif arg.lower() in ("off", "关", "0", "false"):
            self.novel_state.follow = False
            cv.write_info("[跟随] 已关闭自动滚动")
        else:
            cv.write_warn("[用法] /follow on 或 /follow off")
        self._refresh_right_panels()

    def _cmd_panel(self, arg: str) -> None:
        cv = self.query_one(ChatView)
        # /panel ratio <n> 或 /panel show|hide
        parts = arg.split()
        if not parts:
            cv.write_info("用法: /panel show|hide | /panel ratio <左:右>")
            return
        if parts[0].lower() == "show":
            self.right_visible = True
            self.remove_class("right-hidden")
            self._refresh_right_panels()
        elif parts[0].lower() == "hide":
            self.right_visible = False
            self.add_class("right-hidden")
        elif parts[0].lower() == "ratio" and len(parts) >= 2:
            cv.write_info(f"[提示] 比例随窗口宽度自动调整（当前: {self._layout_class}）。手动比例请拖拽终端窗口。")
        else:
            cv.write_warn("[用法] /panel show|hide")

    def _cmd_think(self, arg: str) -> None:
        cv = self.query_one(ChatView)
        if arg.lower() in ("on", "true", "1", "开"):
            self.client.thinking_enabled = True
            cv.write_info("[思考模式] 已开启")
        elif arg.lower() in ("off", "false", "0", "关"):
            self.client.thinking_enabled = False
            cv.write_info("[思考模式] 已关闭")
        else:
            cv.write_warn("[用法] /think on 或 /think off")
        self.refresh_top_bar()

    def _cmd_effort(self, arg: str) -> None:
        cv = self.query_one(ChatView)
        if not arg:
            cv.write_info(f"当前思考强度: {self.client.reasoning_effort or '未设置'}（可选 high/max）")
            return
        if arg.lower() in ("high", "max"):
            self.client.reasoning_effort = arg.lower()
            self.config["reasoning_effort"] = arg.lower()
            save_config(self.config)
            cv.write_info(f"[思考强度] 已设置为 {arg.lower()}")
        else:
            cv.write_warn("[用法] /effort high 或 /effort max")
        self.refresh_top_bar()

    def _cmd_model(self, arg: str) -> None:
        cv = self.query_one(ChatView)
        if not arg:
            cv.write_info(f"当前模型: {self.client.model}")
            for m, desc in AVAILABLE_MODELS.items():
                mk = " ←" if m == self.client.model else ""
                cv.write_info(f"  • {m:<20} - {desc}{mk}")
            return
        if arg not in AVAILABLE_MODELS:
            cv.write_warn(f"未知模型: {arg}")
            return
        self.client.model = arg
        self.config["model"] = arg
        save_config(self.config)
        cv.write_info(f"[模型] 已切换为 {arg}")
        self.refresh_top_bar()

    def _cmd_load(self, arg: str) -> None:
        cv = self.query_one(ChatView)
        arg = _strip_quotes(arg)
        if not arg:
            cv.write_warn("[用法] /load <文件路径>")
            return
        try:
            size = os.path.getsize(arg)
            with open(arg, encoding="utf-8") as f:
                content = f.read()
            self.client.add_message("user", f"[用户加载了文件: {arg}]\n\n以下是文件内容:\n\n{content}")
            cv.write_info(f"[加载文件] {arg}（{size / 1024:.1f} KB，{len(content):,} 字符）")
        except FileNotFoundError:
            cv.write_error(f"文件不存在: {arg}")
        except Exception as e:  # noqa: BLE001
            cv.write_error(f"读取失败: {e}")

    def _cmd_info(self) -> None:
        cv = self.query_one(ChatView)
        tokens = estimate_tokens(self.client.messages)
        tokens += self.client._tool_tokens
        think = "开" if self.client.thinking_enabled else "关"
        max_ctx = self.client.context_max_tokens
        pct = min(100.0, tokens / max_ctx * 100) if max_ctx else 0
        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        special = self.config.get("special_system_prompt", "")
        special_line = f"\n│ 特殊提示词:  {'已设置 (' + str(len(special)) + ' 字)' if special else '未设置'}"
        info = (
            f"┌─ 会话信息 ─────────────────────\n"
            f"│ 模式:        {self.current_mode.display_name}\n"
            f"│ 模型:        {self.client.model}\n"
            f"│ 思考模式:    {think} ({self.client.reasoning_effort or '-'})\n"
            f"│ 当前会话:    {self.current_session.name if self.current_session else '无'}"
            f"（id: {self.current_session.id if self.current_session else '-'}）\n"
            f"│ 会话总数:    {self.session_store.count()}\n"
            f"│ 历史消息:    {len(self.client.messages)} 条\n"
            f"│ 估算 tokens: ~{tokens:,}\n"
            f"│ 上下文占用:  {bar} {pct:.1f}%\n"
            f"│ 剩余空间:    ~{max_ctx - tokens:,} tokens"
            f"{special_line}"
        )
        if self.current_mode_name == "novel":
            info += (
                f"\n│ 小说项目:    {self.novel_state.project_name or '未打开'}\n"
                f"│ 章节进度:    {self.novel_state.done_chapter_count}/{self.novel_state.chapter_count}"
            )
        info += "\n└─────────────────────────────────"
        cv.write_info(info)

    def _cmd_preset(self, arg: str) -> None:
        cv = self.query_one(ChatView)
        parts = arg.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""
        subarg = parts[1] if len(parts) > 1 else ""
        presets = self.chat_mode.presets
        if not sub or sub == "list":
            for name, prompt in presets.items():
                mk = " ← 当前" if name == self.chat_mode.current_preset else ""
                disp = prompt[:40] + "..." if len(prompt) > 40 else prompt
                cv.write_info(f"  • {name:<15} - {disp}{mk}")
        elif sub == "use":
            if subarg not in presets:
                cv.write_error(f"预设 '{subarg}' 不存在")
                return
            self.chat_mode.current_preset = subarg
            if self.current_mode_name == "chat":
                self.client.set_system(apply_special_prompt(self.config, presets[subarg]))
            self.config["current_preset"] = subarg
            save_config(self.config)
            cv.write_info(f"[预设] 已切换到 '{subarg}'")
        elif sub == "add":
            add_parts = subarg.split(maxsplit=1)
            if len(add_parts) < 2:
                cv.write_warn("[用法] /preset add <名称> <提示词>")
                return
            presets[add_parts[0]] = add_parts[1]
            self.config["presets"] = presets
            save_config(self.config)
            cv.write_info(f"[预设] 已添加 '{add_parts[0]}'")
        elif sub == "del":
            if subarg not in presets:
                cv.write_error(f"预设 '{subarg}' 不存在")
                return
            if subarg == self.chat_mode.current_preset:
                cv.write_error("不能删除当前使用的预设")
                return
            del presets[subarg]
            self.config["presets"] = presets
            save_config(self.config)
            cv.write_info(f"[预设] 已删除 '{subarg}'")
        elif sub == "show":
            if subarg not in presets:
                cv.write_error(f"预设 '{subarg}' 不存在")
                return
            cv.write_info(f"预设 '{subarg}':\n{'─' * 40}\n{presets[subarg]}\n{'─' * 40}")
        else:
            cv.write_warn("可用: list, use, add, del, show")

    def _cmd_special(self, arg: str) -> None:
        """特殊系统提示词：/special [内容|clear]。

        特殊提示词会插入到所有 system prompt 最前面（含主对话/章节摘要/对话摘要），
        后接换行。用于全局指令如"始终用简体中文"。
        """
        cv = self.query_one(ChatView)
        if not arg:
            current = self.config.get("special_system_prompt", "")
            if current:
                cv.write_info(f"当前特殊提示词:\n{'─' * 40}\n{current}\n{'─' * 40}")
            else:
                cv.write_info("当前未设置特殊提示词")
            cv.write_info("用法: /special <内容> 设置 | /special clear 清空")
            return
        if arg.lower() == "clear":
            self.config["special_system_prompt"] = ""
            save_config(self.config)
            self._init_system_prompt()
            cv.write_info("[特殊提示词] 已清空")
            return
        self.config["special_system_prompt"] = arg
        save_config(self.config)
        self._init_system_prompt()
        cv.write_info(f"[特殊提示词] 已设置: {arg}")

    # ── 会话管理 ──
    def _sync_current_session(self) -> None:
        """把 client 当前消息 + NovelState 会话级状态同步到 current_session 并持久化。"""
        if not self.current_session:
            return
        self.current_session.messages = list(self.client.messages)
        self.current_session.mode = self.current_mode_name
        self.current_session.novel_project = self.novel_state.project_name
        # 同步会话级状态（常驻记忆 + 创作进度）
        if self.current_session.mode == "novel":
            session_state = self.novel_state.save_session_state()
            self.current_session.novel_memory = session_state["novel_memory"]
            self.current_session.novel_progress = session_state["novel_progress"]
        self.current_session.touch()
        self.session_store.save()

    def _switch_session_store(self, path: Path) -> None:
        """切换 SessionStore 到新路径并恢复/新建会话。

        调用方需在调用前完成当前会话的保存（_sync_current_session），
        且保存时项目名/模式名应保持旧值，避免会话元数据错乱。

        novel 模式优先恢复该项目最近使用的会话（按 updated_at 降序），
        无历史会话时才新建空会话。chat 模式始终新建。
        """
        self.session_store = SessionStore(path)
        project = self.novel_state.project_name if self.current_mode_name == "novel" else None

        # novel 模式：尝试恢复该项目最近的会话
        if self.current_mode_name == "novel" and project:
            recent = self.session_store.list_sessions(mode="novel", project=project)
            if recent:
                self.current_session = recent[0]
                self.config["current_session_id"] = self.current_session.id
                save_config(self.config)
                self.client.load_messages(self.current_session.messages)
                self.novel_state.restore_session_state(
                    {
                        "novel_memory": self.current_session.novel_memory,
                        "novel_progress": self.current_session.novel_progress,
                    }
                )
                self._init_system_prompt()
                self._refresh_right_panels()
                return

        # 无历史会话：新建空会话
        self.current_session = self.session_store.create("新会话", self.current_mode_name, project)
        self.config["current_session_id"] = self.current_session.id
        save_config(self.config)
        self.client.load_messages([])
        if self.current_mode_name == "novel":
            self.novel_state.reset_session_state()
        self._init_system_prompt()
        self._refresh_right_panels()

    def _cmd_new_session(self, arg: str) -> None:
        """新建会话：/new [名称]。"""
        cv = self.query_one(ChatView)
        # 先保存当前会话
        self._sync_current_session()
        name = arg.strip() if arg.strip() else "新会话"
        # novel 模式下绑定当前项目
        project = self.novel_state.project_name if self.current_mode_name == "novel" else None
        session = self.session_store.create(name, self.current_mode_name, project)
        self.current_session = session
        self.config["current_session_id"] = session.id
        save_config(self.config)
        # 重置 client 上下文
        self.client.load_messages([])
        # novel 模式下重置会话级状态（保留项目级数据 chapter_count/chapters）
        if self.current_mode_name == "novel":
            self.novel_state.reset_session_state()
        self._init_system_prompt()
        self._refresh_right_panels()
        cv.write_info(f"[新会话] 已创建：{session.name}（id: {session.id}）")
        cv.write_separator()
        self.refresh_top_bar()

    def _cmd_list_sessions(self) -> None:
        """列出历史会话（弹出模态屏选择），按当前模式/项目过滤。

        - chat 模式：只显示 chat 会话
        - novel 模式：只显示当前项目的 novel 会话
        """
        if self.current_mode_name == "novel":
            project = self.novel_state.project_name
            sessions = self.session_store.list_sessions(mode="novel", project=project)
        else:
            sessions = self.session_store.list_sessions(mode="chat")
        current_id = self.current_session.id if self.current_session else None
        self.push_screen(
            SessionsScreen(sessions, current_id),
            callback=self._on_sessions_screen_result,
        )

    def _on_sessions_screen_result(self, result: str | None) -> None:
        """模态屏返回值处理。"""
        if result is None:
            return
        if result == "__new__":
            self._cmd_new_session("")
            return
        if result.startswith("__delete__:"):
            sid = result.split(":", 1)[1]
            self._cmd_delete_session(sid)
            return
        # 载入选中的会话
        self._cmd_load_session(result)

    def _cmd_load_session(self, sid: str) -> None:
        """载入指定 ID 的会话，恢复消息历史 + 会话级状态。"""
        cv = self.query_one(ChatView)
        session = self.session_store.get(sid)
        if session is None:
            cv.write_warn(f"[错误] 找不到会话: {sid}")
            return
        # 先保存当前会话
        self._sync_current_session()
        # 切换
        self.current_session = session
        self.config["current_session_id"] = session.id
        save_config(self.config)
        self.client.load_messages(session.messages)
        # 切换到该会话的模式
        if session.mode in self.modes and session.mode != self.current_mode_name:
            self._switch_mode(session.mode)
        # 恢复会话级状态（常驻记忆 + 创作进度）
        if session.mode == "novel":
            self.novel_state.restore_session_state(
                {
                    "novel_memory": session.novel_memory,
                    "novel_progress": session.novel_progress,
                }
            )
            # 项目级数据从 project_state.json 加载（若项目已打开）
            if self.novel_state.project_root is not None:
                ProjectStateStore.load_to_state(self.novel_state)
        self._init_system_prompt()
        self._refresh_right_panels()
        cv.write_info(
            f"[载入会话] {session.name}（{len(session.messages)} 条消息，模式: {session.mode}）"
        )
        cv.write_separator()
        self.refresh_top_bar()

    def _cmd_plan(self, arg: str) -> None:
        """/plan <请求>：计划模式——模型先输出计划到 .Project/ 文件，确认后再执行。"""
        cv = self.query_one(ChatView)
        if not arg.strip():
            cv.write_warn("[用法] /plan <请求描述>")
            return
        # 注入计划上下文
        plan_prompt = (
            "[计划模式] 用户要求你先制定计划再执行。请：\n"
            "1. 用 write_file 在 .Project/ 目录下创建一个 plan_xxx.md 文件，详细列出执行步骤\n"
            "2. 计划写完后，向用户展示摘要，并**明确询问是否确认执行**（等待用户回复后再行动）\n"
            "3. 用户确认后，先用 list_project_files 查看所有计划文件简介，\n"
            "   然后用 read_project_file 读取你需要执行的计划文件全文，按计划逐步执行\n"
            "4. 执行过程中，用待办工具实时更新进度\n\n"
            f"用户请求: {arg.strip()}"
        )
        self._start_chat(plan_prompt)
        return

    def _update_plan_index(self) -> None:
        """扫描 .Project/ 下的 .md 文件，生成 plans_index.md 简介索引。"""
        if self.novel_state.project_root is None:
            return
        proj_dir = self.novel_state.project_root / ".Project"
        if not proj_dir.exists():
            return
        entries = []
        for f in sorted(proj_dir.iterdir(), key=lambda p: p.name.lower()):
            if not f.is_file() or not f.name.endswith(".md") or f.name == "plans_index.md":
                continue
            try:
                content = f.read_text(encoding="utf-8")
                first_para = content.strip().split("\n\n")[0] if content.strip() else "(空文件)"
                # 取前 120 字作为简介
                summary = first_para[:120].replace("\n", " ").strip()
                entries.append(f"- **{f.name}**: {summary}")
            except Exception:
                entries.append(f"- **{f.name}**: (读取失败)")
        index_content = "# 计划文件索引\n\n" + ("\n".join(entries) if entries else "暂无计划文件\n")
        try:
            (proj_dir / "plans_index.md").write_text(index_content, encoding="utf-8")
        except Exception:
            pass

    def _cmd_rename_session(self, arg: str) -> None:
        """重命名当前会话：/rename <新名称>。"""
        cv = self.query_one(ChatView)
        if not arg.strip():
            cv.write_warn("[用法] /rename <新名称>")
            return
        if not self.current_session:
            cv.write_warn("[错误] 当前无活动会话")
            return
        old_name = self.current_session.name
        self.session_store.rename(self.current_session.id, arg.strip())
        cv.write_info(f"[重命名] {old_name} → {arg.strip()}")
        self.refresh_top_bar()
        return

    def _cmd_delete_session(self, arg: str) -> None:
        """删除会话：/delete <id>。"""
        cv = self.query_one(ChatView)
        sid = arg.strip()
        if not sid:
            cv.write_warn("[用法] /delete <会话id>（用 /sessions 查看）")
            return
        if sid == self.current_session.id if self.current_session else False:
            cv.write_warn("[错误] 不能删除当前活动会话，请先 /new 或 /load 切换")
            return
        if self.session_store.delete(sid):
            cv.write_info(f"[已删除] 会话 {sid}")
        else:
            cv.write_warn(f"[错误] 找不到会话: {sid}")

    # ── 聊天 worker（异步流式 + agent 回路）──
    def _start_chat(self, user_input: str) -> None:
        cv = self.query_one(ChatView)
        cv.write_user(user_input)
        self._busy = True
        self._sync_current_session()
        self._persist_history()
        self._chat_worker(user_input)

    @work(exclusive=True, name="chat")
    async def _chat_worker(self, user_input: str) -> None:
        tools = self.current_mode.get_tools()
        success = False
        try:
            success = await self._run_agent_round(user_input, tools, round_idx=0)
        finally:
            self._busy = False
            self._sync_current_session()
            self._persist_history()
            self.refresh_top_bar()
            # agent 正常结束时，才后台处理待摘要章节（失败时不清除队列，留给下次成功）
            if success and self._pending_chapter_summaries and self.auto_summarize_on_chapter_done:
                self._summarize_pending_chapters()

    async def _run_agent_round(self, user_input: str | None, tools: list[dict], round_idx: int) -> bool:
        """单轮 agent：发送输入/续写，处理事件，必要时递归下一轮。

        async worker 跑在主事件循环线程，可直接操作 UI，无需 call_from_thread。
        返回 True 表示本轮及后续递归均正常完成，False 表示遇到错误。
        """
        if round_idx >= self.max_agent_rounds:
            self.query_one(ChatView).write_warn(f"[停止] 已达最大轮数 {self.max_agent_rounds}")
            return True
        # 每轮开始前刷新上下文占用统计
        self.refresh_top_bar()
        # 记录本轮开始前的 token 数，用于结束后展示增量
        _tokens_before = estimate_tokens(self.client.messages) + self.client._tool_tokens
        # 每轮开始前检查上下文水位，必要时异步摘要早期对话
        await self._maybe_compress_context()
        # 每 2 轮注入一次 set_progress 提醒（不再依赖模型记住提示词）
        if self.current_mode_name == "novel" and round_idx % 2 == 0 and round_idx > 0:
            self.client.add_message("user", "[系统提醒] 请调用 set_progress 更新当前进度条。")
        cv = self.query_one(ChatView)
        thinking_started = False
        answer_started = False
        had_tool_calls = False
        # 本轮已宣告"正在调用"的工具名集合（同名工具不同参数也只宣告一次）
        _announced_tools: set[str] = set()

        # 选择入口：首轮用 chat(user_input)，后续轮用 continue_after_tools
        if user_input is not None:
            stream = self.client.chat(user_input, tools)
        else:
            stream = self.client.continue_after_tools(tools)

        async for ev in stream:
            if ev.kind == "thinking":
                if not thinking_started:
                    thinking_started = True
                    cv.write_thinking_start()
                cv.write_thinking(ev.text)
            elif ev.kind == "answer":
                if thinking_started and not answer_started:
                    cv.write_thinking_end()
                    cv.write_answer_start()
                    answer_started = True
                elif not answer_started:
                    cv.write_answer_start()
                    answer_started = True
                cv.write_answer(ev.text)
            elif ev.kind == "tool_streaming":
                # 所有工具首次收到参数时，立即在聊天区宣告"正在调用..."
                if ev.tool_name not in _announced_tools:
                    _announced_tools.add(ev.tool_name)
                    cv.write_tool_calling(ev.tool_name)
                # 文件写入类工具：流式更新文件预览面板
                self._on_tool_streaming(ev.tool_name, ev.tool_args)
                # 让出控制权，确保 Textual 在下一轮事件前有机会重绘 UI
                await asyncio.sleep(0)
            elif ev.kind == "tool_call":
                had_tool_calls = True
                # 工具调用前先关闭思考块，避免工具调用嵌在未关闭的思考框里
                if thinking_started and not answer_started:
                    cv.write_thinking_end()
                # 流式预览结束，工具真正执行
                self._on_tool_streaming_end()
                # 执行工具（同步，操作 NovelState 与真实文件）
                summary = self.tool_executor.summary(ev.tool_name, ev.tool_args)
                result = self.tool_executor.dispatch(ev.tool_name, ev.tool_args)
                cv.write_tool_call(f"{summary} → {result}")
                # 工具执行后立即刷新右侧面板
                self._refresh_right_panels()
                # 回传工具结果
                self.client.add_tool_result(ev.tool_call_id, result)
                # 常驻记忆工具：刷新 system prompt 以注入最新记忆
                if ev.tool_name in _MEMORY_TOOLS:
                    self._init_system_prompt()
                # 章节结构变更工具：同步项目级状态到 .Project/project_state.json
                if ev.tool_name in {"set_chapter_count", "set_current_chapter", "mark_chapter_done", "set_progress"}:
                    ProjectStateStore.save_from_state(self.novel_state)
                # 计划文件写入 .Project/：更新索引 + 记录待确认计划
                if ev.tool_name in {"write_file", "create_novel_file"}:
                    try:
                        args = json.loads(ev.tool_args) if ev.tool_args.strip() else {}
                        fp = args.get("path", "")
                        if fp.startswith(".Project/") and fp.endswith(".md") and fp != ".Project/plans_index.md":
                            self._pending_plan_file = fp
                            self._update_plan_index()
                    except Exception:
                        pass
                # 即时同步会话状态到磁盘，确保工具修改的待办/记忆/进度不会因中途崩溃而丢失
                self._sync_current_session()
                # 工具调用完成后刷新上下文占用（消息已增长）
                self.refresh_top_bar()
                # mark_chapter_done：入队待摘要章节
                if ev.tool_name == "mark_chapter_done" and self.auto_summarize_on_chapter_done:
                    try:
                        args = json.loads(ev.tool_args) if ev.tool_args.strip() else {}
                        idx = int(args.get("index", 0))
                        if idx > 0 and idx not in self.novel_state.chapter_summaries:
                            if idx not in self._pending_chapter_summaries:
                                self._pending_chapter_summaries.append(idx)
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
            elif ev.kind == "error":
                cv.write_error(f"[错误] {ev.error}")
                return False
            elif ev.kind == "done":
                if thinking_started and not answer_started:
                    cv.write_thinking_end()
                if answer_started:
                    cv.write_separator()
                # 本轮结束：展示新增 token 数及上下文占用
                _tokens_after = estimate_tokens(self.client.messages) + self.client._tool_tokens
                _delta = _tokens_after - _tokens_before
                _max = self.client.context_max_tokens
                _pct = (_tokens_after / _max * 100) if _max else 0
                cv.write(Text.assemble(
                    ("[sys] ", "dim cyan"),
                    ("++", "green"),
                    (f" ~{_delta:,} tokens | ", ""),
                    ("context:", "yellow"),
                    (f" {_tokens_after:,}/{_max:,} ({_pct:.2f}%)", ""),
                ))

        # agent 回路：若有工具调用，继续下一轮
        if had_tool_calls:
            return await self._run_agent_round(None, tools, round_idx + 1)
        return True

    async def _maybe_compress_context(self) -> None:
        """如果上下文处于压缩档（compress_threshold ≤ ratio < critical_threshold），
        异步摘要早期对话并注入摘要，删除早期原文。

        警戒档和紧急档已由 client._manage_context 同步处理（精简/截断），
        此处只处理需要异步调用模型的压缩档。
        """
        ratio = self.client.context_ratio()
        if ratio < self.client.compress_threshold:
            return
        if ratio >= self.client.critical_threshold:
            # 紧急档已被 _force_truncate 处理，无需摘要
            return
        cv = self.query_one(ChatView)
        cv.write_warn(f"[压缩] 上下文占用 {ratio * 100:.1f}%，正在生成早期对话摘要...")
        summary = await self._summarize_early_dialogue()
        if summary:
            cv.write_info(f"[压缩] 已生成摘要（{len(summary)} 字），早期对话已压缩")
            self.refresh_top_bar()
        else:
            cv.write_warn("[压缩] 摘要生成失败，改用强制截断")
            self.client._force_truncate()
            self.refresh_top_bar()

    async def _summarize_early_dialogue(self) -> str:
        """摘要滑动窗口之外的早期对话，注入摘要并删除原文。

        流程：
        1. 分离 system 消息与其它消息
        2. 拼接早期消息为文本（每条截断 500 字防过长）
        3. 调用 client.summarize_text 生成摘要（用 DIALOGUE_SUMMARY_SYSTEM_PROMPT）
        4. 把摘要作为 system 消息注入，删除早期原文，保留最近 N 轮
        """
        from .config import DIALOGUE_SUMMARY_SYSTEM_PROMPT

        keep_count = self.client.sliding_window_rounds * 4
        # 分离 system 和其他消息
        system_msgs: list[dict[str, Any]] = []
        rest_msgs: list[dict[str, Any]] = []
        for m in self.client.messages:
            if m.get("role") == "system":
                system_msgs.append(m)
            else:
                rest_msgs.append(m)
        if len(rest_msgs) <= keep_count:
            return ""
        early = rest_msgs[:-keep_count] if keep_count > 0 else rest_msgs
        # 拼接早期消息为文本
        lines: list[str] = []
        for m in early:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, str) and content:
                lines.append(f"[{role}] {content[:500]}")
            elif m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                    lines.append(f"[assistant/tool_call] {fn.get('name', '?')}")
        if not lines:
            return ""
        dialogue_text = "\n".join(lines)[:8000]  # 限制摘要输入长度
        # 调用模型摘要（system prompt 走 apply_special_prompt）
        sys_prompt = apply_special_prompt(self.config, DIALOGUE_SUMMARY_SYSTEM_PROMPT)
        summary = await self.client.summarize_text(sys_prompt, dialogue_text)
        if not summary:
            return ""
        # 把摘要作为 system 消息注入（在原 system 之后），保留最近 keep_count 条
        summary_msg: dict[str, Any] = {
            "role": "system",
            "content": f"【早期对话摘要】\n{summary}",
        }
        recent = rest_msgs[-keep_count:] if keep_count > 0 else []
        self.client.messages = system_msgs + [summary_msg] + recent
        return summary

    @work(name="chapter_summary")
    async def _summarize_pending_chapters(self) -> None:
        """为待摘要的章节生成摘要（后台 worker，不阻塞主对话）。

        使用 CHAPTER_SUMMARY_SYSTEM_PROMPT，读取章节文件全文作为输入。
        失败时用规则化兜底（首段+末段）。
        """
        from .config import CHAPTER_SUMMARY_SYSTEM_PROMPT

        cv = self.query_one(ChatView)
        while self._pending_chapter_summaries:
            idx = self._pending_chapter_summaries.pop(0)
            # 已有摘要则跳过
            if idx in self.novel_state.chapter_summaries:
                continue
            content = self._read_chapter_file(idx)
            if not content:
                cv.write_warn(f"[摘要] 第 {idx} 章文件未找到，跳过摘要")
                continue
            cv.write_info(f"[摘要] 正在生成第 {idx} 章摘要...")
            sys_prompt = apply_special_prompt(self.config, CHAPTER_SUMMARY_SYSTEM_PROMPT)
            summary = await self.client.summarize_text(
                sys_prompt, content, max_chars=self.chapter_summary_max_chars
            )
            if summary:
                self.novel_state.set_chapter_summary(idx, summary)
                cv.write_info(f"[摘要] 第 {idx} 章摘要已保存（{len(summary)} 字）")
                # 刷新 system prompt 以注入新摘要
                self._init_system_prompt()
                self._sync_current_session()
            else:
                # 兜底：规则化摘要
                fallback = self._fallback_chapter_summary(content)
                self.novel_state.set_chapter_summary(idx, fallback)
                cv.write_warn(f"[摘要] 第 {idx} 章摘要生成失败，已用规则化兜底")
                self._init_system_prompt()
                self._sync_current_session()

    def _read_chapter_file(self, index: int) -> str:
        """读取指定章节文件全文，返回空字符串表示未找到。"""
        if self.novel_state.project_root is None:
            return ""
        candidates = [
            self.novel_state.project_root / f"ch{index:02d}.md",
            self.novel_state.project_root / f"ch{index}.md",
            self.novel_state.project_root / f"第{index}章.md",
        ]
        for path in candidates:
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8")
                except Exception:  # noqa: BLE001
                    return ""
        return ""

    def _fallback_chapter_summary(self, content: str) -> str:
        """规则化章节摘要兜底：首段 + 末段 + 包含人名的句子。"""
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not paragraphs:
            return content[:200]
        parts = [paragraphs[0][:200]]
        if len(paragraphs) > 1:
            parts.append(paragraphs[-1][:200])
        # 找包含常见人名标记的句子（启发式）
        for p in paragraphs[1:-1]:
            if any(c in p for c in "说道：说：想道") and len(parts) < 4:
                parts.append(p[:150])
        return "...".join(parts)[: self.chapter_summary_max_chars]

    def _cv_write_warn(self, text: str) -> None:
        self.query_one(ChatView).write_warn(text)

    # ── 持久化 ──
    def _persist_config(self) -> dict[str, Any]:
        cfg = dict(self.config)
        cfg["model"] = self.client.model
        cfg["reasoning_effort"] = self.client.reasoning_effort
        cfg["thinking_enabled"] = self.client.thinking_enabled
        cfg["presets"] = self.chat_mode.presets
        cfg["current_preset"] = self.chat_mode.current_preset
        cfg["current_mode"] = self.current_mode_name
        # history 字段保留向后兼容（实际多会话存储在 sessions.json）
        cfg["history"] = self.client.messages
        if self.current_session:
            cfg["current_session_id"] = self.current_session.id
        return cfg

    def _persist_history(self) -> None:
        save_config(self._persist_config())


def main() -> None:
    """入口：检查 API key 后启动 TUI。"""
    cfg = load_config()
    if not cfg.get("api_key"):
        print("错误: 未设置 DEEPSEEK_API_KEY")
        print("请设置环境变量: set DEEPSEEK_API_KEY=your_key_here")
        raise SystemExit(1)
    app = KAPurnTUI()
    app.run()


if __name__ == "__main__":
    main()
