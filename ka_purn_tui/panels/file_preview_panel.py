# ── 文件实时预览面板（核心，做大）─────────────────────────
"""FilePreviewPanel：像代码编辑器一样实时显示模型正在操作的文件内容。

fraction 6（约占右侧 50% 高度），追加内容时自动滚到底部（follow 开启时）。

双模式预览：
  - model 模式：模型操作文件时自动切换，显示前 1000 行（head）
  - user 模式：用户点击文件树时切换，显示完整内容（无行数限制）
  - 流式模式：模型 arguments 累积时逐字显示，不截断（实时观看写入过程）

用户点击模型正在编辑的文件时，切回 model 模式恢复实时流式进度。
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, RichLog


class FilePreviewPanel(Vertical):
    """文件实时预览面板（fraction 6，最大）。"""

    DEFAULT_CSS = """
    FilePreviewPanel {
        border: round $accent;
        height: 6fr;
        min-height: 8;
        padding: 0;
    }
    FilePreviewPanel > Label {
        dock: top;
        height: 1;
        background: $accent 20%;
        color: $text;
        padding: 0 1;
    }
    FilePreviewPanel > RichLog {
        height: 1fr;
        border: none;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    """

    title = "文件预览"

    # 模型模式：显示前 N 行（head），避免超大文件卡顿
    MAX_PREVIEW_LINES = 1000

    def __init__(self) -> None:
        super().__init__()
        self._state = None
        self._follow = True
        # 流式状态
        self._streaming = False
        self._stream_path: str | None = None
        self._stream_base: str = ""  # append 模式下文件已有内容

    def compose(self) -> ComposeResult:
        yield Label("文件预览（无）", id="preview-title")
        yield RichLog(id="preview-log", highlight=False, markup=True, auto_scroll=False, wrap=True)

    @property
    def log(self) -> RichLog:
        return self.query_one("#preview-log", RichLog)

    @property
    def title_label(self) -> Label:
        return self.query_one("#preview-title", Label)

    def set_follow(self, follow: bool) -> None:
        self._follow = follow

    # ── 最终态刷新（工具执行后 / 用户点击后）──
    def refresh_state(self, state) -> None:  # type: ignore[no-untyped-def]
        """用最新状态刷新预览（根据 preview_source 选择模式）。"""
        self._state = state
        self._follow = state.follow
        self._streaming = False  # 退出流式模式
        if not self.is_mounted or not self.query("#preview-title"):
            self.call_after_refresh(self._render_state)
            return
        self._render_state()

    def _render_state(self) -> None:
        if self._state is None:
            return
        path = self._state.preview_file
        content = self._state.preview_content
        source = self._state.preview_source
        try:
            if not path:
                self.title_label.update("文件预览（无）")
                self.log.clear()
                return
            icon = "▶" if source == "model" else "▷"
            self.title_label.update(f"{icon} {path}  ({len(content)} 字, {source})")
        except Exception:
            return
        # model 模式限制前 1000 行，user 模式无限制
        max_lines = self.MAX_PREVIEW_LINES if source == "model" else None
        self._write_to_log(content, max_lines=max_lines)

    def _write_to_log(self, content: str, max_lines: int | None = None) -> None:
        """渲染内容到 RichLog。max_lines=None 表示不截断。"""
        self.log.clear()
        if not content.strip():
            self.log.write("[dim]（空文件）[/dim]")
            return
        lines = content.splitlines()
        if max_lines is not None and len(lines) > max_lines:
            self.log.write(f"[dim]...（共 {len(lines)} 行，仅显示前 {max_lines} 行）[/dim]")
            lines = lines[:max_lines]
        for ln in lines:
            self.log.write(Text(ln))
        if self._follow:
            self.log.scroll_end()

    # ── 流式实时更新（arguments 累积时）──
    def streaming_update(self, tool_name: str, path: str, partial_text: str) -> None:
        """流式更新预览：逐句显示模型正在写入的内容。

        策略：每次收到新内容时，清空 RichLog 并按 \\n 拆行全量重写。
        RichLog.write() 每次调用必定创建新显示行，所以只有全量重写才能保证
        换行正确的同时实现实时流式效果。性能：流式内容通常几百到几千字，
        每次重写开销在毫秒级，不会造成可感知的延迟。

        - append_to_file: 显示 文件已有内容 + partial_text
        - create_novel_file/write_file: 显示 partial_text
        - edit_file: 显示 partial_text（编辑片段）
        """
        if not self.is_mounted:
            return

        # 路径变化或首次：读取 append 模式的文件已有内容
        if path != self._stream_path:
            self._stream_path = path
            self._streaming = True
            if tool_name == "append_to_file" and self._state is not None:
                root = self._state.project_root
                if root is not None:
                    fp = root / path
                    self._stream_base = fp.read_text(encoding="utf-8") if fp.exists() and fp.is_file() else ""
                else:
                    self._stream_base = ""
            else:
                self._stream_base = ""

        # 组装完整内容
        if tool_name == "append_to_file":
            display = self._stream_base + partial_text
        else:
            display = partial_text

        # 更新标题
        try:
            self.title_label.update(f"» {path}  (流式 {len(display)} 字)")
        except Exception:
            pass

        # 清空并按 \\n 拆行全量重写
        self.log.clear()
        if not display.strip():
            self.log.write("[dim]（空文件）[/dim]")
        else:
            lines = display.split("\n")
            for ln in lines[:-1]:
                self.log.write(Text(ln) if ln else Text(""))
            if lines[-1]:
                self.log.write(Text(lines[-1]))

        if self._follow:
            self.log.scroll_end()
        self.log.refresh()

    def streaming_end(self) -> None:
        """流式结束：重置状态。"""
        self._streaming = False
        self._stream_path = None
        self._stream_base = ""
