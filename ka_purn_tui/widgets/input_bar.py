# ── 底部输入栏 ─────────────────────────────────
"""InputBar：基于 textual TextArea 的多行输入栏，Enter 提交、Shift+Enter 换行，支持斜杠命令。

功能：
  - 多行编辑：Shift+Enter 换行，Enter 提交
  - ↑/↓ 在光标位于首行/末行时翻阅历史输入；补全列表激活时改为上下选择候选
  - Tab 用当前高亮候选补全斜杠命令（预选中 + 用法提示）
  - 历史持久化（由 App 通过 config.json 管理）

设计说明：传统终端无法区分 Shift+Enter 与 Enter（都发送 0x0D），
但 Windows API GetAsyncKeyState 可在 OS 层面实时查询 Shift 键按下状态，
从而在收到 Enter 时判断是"Enter 提交"还是"Shift+Enter 换行"。
此方案完全绕过终端协议限制。
"""

from __future__ import annotations

import ctypes

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, OptionList, Static, TextArea

from ..commands import match_commands

# Windows 虚拟键码
VK_SHIFT = 0x10
VK_CONTROL = 0x11


def _is_key_held(vk: int) -> bool:
    """检测某个虚拟键当前是否被按住（OS 级查询，绕过终端协议）。"""
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


class HistoryInput(TextArea):
    """带历史导航与 Tab 补全的多行输入框。

    Enter 提交，Shift+Enter 换行（借助 GetAsyncKeyState 检测 Shift 键）。
    上/下键在光标位于首行/末行时翻阅历史输入；补全列表激活时选择候选。
    历史记录由外部通过 set_history / input_history 属性管理持久化。
    """

    # 无组合键绑定，所有处理在 on_key 中手动完成。
    BINDINGS = []

    def __init__(self, *args: object, history: list[str] | None = None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._history: list[str] = list(history or [])
        # 当前历史游标位置：len(history) 表示"草稿区"（未提交的当前输入）
        self._history_index: int = len(self._history)
        # 草稿：用户在浏览历史时未提交的输入，按↓回到末尾时恢复
        self._draft: str = ""
        # 补全状态
        self._completion_index: int = 0
        # 回调：通知 InputBar 更新补全提示
        self._on_completion_change: callable | None = None  # type: ignore[type-arg]
        # 回调：提交（Shift+Enter 触发，由 App 注入）
        self._on_submit: callable | None = None  # type: ignore[type-arg]

    def set_completion_callback(self, callback: callable) -> None:  # type: ignore[type-arg]
        """设置补全变化时的回调（由 InputBar 注入）。"""
        self._on_completion_change = callback

    def set_submit_callback(self, callback: callable) -> None:  # type: ignore[type-arg]
        """设置提交回调（由 App 注入，Shift+Enter 触发）。"""
        self._on_submit = callback

    # ── 按键处理 ──
    def on_key(self, event: events.Key) -> None:
        # Enter：用 GetAsyncKeyState 检测 Shift 是否被按住（OS 级，绕过终端协议）
        if event.key == "enter":
            if _is_key_held(VK_SHIFT):
                # Shift+Enter → 换行（手动插入换行符）
                event.prevent_default()
                event.stop()
                self.replace("\n", self.cursor_location, self.cursor_location)
                row, _ = self.cursor_location
                self.move_cursor((row + 1, 0))
                return
            # 纯 Enter → 提交
            event.prevent_default()
            event.stop()
            if self._on_submit:
                self._on_submit()
            return
        if event.key == "up":
            # 补全列表激活时优先选择候选
            if self._on_completion_change and self._on_completion_change("up"):
                event.prevent_default()
                event.stop()
                return
            # 光标在首行时翻阅历史，否则走默认光标移动
            if self.cursor_at_first_line:
                self._navigate(-1)
                event.prevent_default()
                event.stop()
        elif event.key == "down":
            if self._on_completion_change and self._on_completion_change("down"):
                event.prevent_default()
                event.stop()
                return
            # 光标在末行时翻阅历史，否则走默认光标移动
            if self.cursor_at_last_line:
                self._navigate(1)
                event.prevent_default()
                event.stop()
        elif event.key == "tab":
            # Tab 补全：由 InputBar 的补全逻辑处理，阻止默认 Tab 缩进
            handled = self._try_complete()
            if handled:
                event.prevent_default()
                event.stop()
        elif event.key == "escape":
            # Esc 关闭补全提示
            if self._on_completion_change and self._on_completion_change("escape"):
                event.prevent_default()
                event.stop()

    def _navigate(self, direction: int) -> None:
        """direction<0 向上（更早的历史），direction>0 向下（更新的历史）。"""
        if direction < 0:
            if not self._history or self._history_index <= 0:
                return
            # 进入历史前保存当前草稿
            if self._history_index == len(self._history):
                self._draft = self.text
            self._history_index -= 1
            self.load_text(self._history[self._history_index])
            self._move_cursor_to_end()
        else:
            if self._history_index >= len(self._history):
                return
            self._history_index += 1
            if self._history_index == len(self._history):
                # 回到草稿区
                self.load_text(self._draft)
            else:
                self.load_text(self._history[self._history_index])
            self._move_cursor_to_end()

    def _move_cursor_to_end(self) -> None:
        """移动光标到文本末尾。"""
        line_count = self.document.line_count
        last_line = self.document[line_count - 1] if line_count > 0 else ""
        self.move_cursor((line_count - 1, len(last_line)))

    # ── Tab 补全 ──
    def _try_complete(self) -> bool:
        """尝试 Tab 补全。返回 True 表示已处理。"""
        if not self._on_completion_change:
            return False
        return self._on_completion_change("tab")

    # ── 历史管理 ──
    def record_history(self, value: str) -> None:
        """提交后记录一条历史。空值与连续重复会被忽略。"""
        if not value.strip():
            return
        # 避免连续重复记录
        if self._history and self._history[-1] == value:
            self._history_index = len(self._history)
            self._draft = ""
            return
        self._history.append(value)
        self._history_index = len(self._history)
        self._draft = ""

    @property
    def input_history(self) -> list[str]:
        """返回历史列表的副本。"""
        return list(self._history)

    def set_history(self, history: list[str]) -> None:
        """从外部加载历史（启动时从 config 恢复）。"""
        self._history = list(history)
        self._history_index = len(self._history)
        self._draft = ""

    def clear(self) -> None:
        """清空输入框。"""
        self.load_text("")
        self._draft = ""


class InputBar(Vertical):
    """输入栏：补全提示行 + 提示符 + 多行输入框。"""

    DEFAULT_CSS = """
    InputBar {
        height: auto;
        padding: 0;
        border: none;
    }
    InputBar > Horizontal {
        height: auto;
        padding: 0;
    }
    InputBar > Horizontal > Label {
        width: 3;
        height: 5;
        color: $success;
        content-align: left middle;
        padding: 0 0 0 1;
    }
    InputBar > Horizontal > TextArea {
        width: 1fr;
        height: 5;
        border: round $primary;
        padding: 0 1;
    }
    InputBar > Horizontal > TextArea:focus {
        border: round $accent;
    }
    #completion-hint {
        height: auto;
        max-height: 9;
        padding: 0 1;
        background: $boost;
        display: none;
    }
    #completion-hint.visible {
        display: block;
    }
    #completion-list {
        height: 6;
        border: none;
        padding: 0;
        background: transparent;
        color: $text;
    }
    #completion-list:focus {
        border: none;
    }
    #completion-list > .option-list--option {
        padding: 0;
    }
    #completion-list > .option-list--option-highlighted {
        color: $accent;
        background: transparent;
        text-style: bold;
    }
    #completion-detail {
        height: auto;
        color: $text-muted;
        padding-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._current_mode: str = "chat"
        # 当前匹配的命令列表
        self._matches: list[tuple[str, dict]] = []  # type: ignore[type-arg]
        self._completion_index: int = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="completion-hint"):
            option_list = OptionList(id="completion-list")
            option_list.can_focus = False
            yield option_list
            yield Static("", id="completion-detail")
        with Horizontal():
            yield Label(">")
            yield HistoryInput(id="chat-input", soft_wrap=True, show_line_numbers=False)

    def on_mount(self) -> None:
        input_widget = self.query_one(HistoryInput)
        input_widget.set_completion_callback(self._handle_completion_request)

    @property
    def input(self) -> HistoryInput:
        return self.query_one("#chat-input", HistoryInput)

    def set_mode(self, mode: str) -> None:
        """设置当前模式（用于过滤模式专属命令）。"""
        self._current_mode = mode

    def focus_input(self) -> None:
        self.input.focus()

    def clear(self) -> None:
        self.input.clear()

    # ── 补全逻辑 ──
    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """输入变化时更新补全提示。"""
        if event.text_area.id != "chat-input":
            return
        value = event.text_area.text
        # 命令补全仅在第一行以 / 开头且无空格时触发
        first_line = value.split("\n", 1)[0]
        if value.startswith("/") and "\n" not in value and " " not in value:
            # 命令补全模式
            self._matches = match_commands(value, self._current_mode)
            self._completion_index = 0
            self._update_hint()
        else:
            self._matches = []
            self._update_hint()

    def _handle_completion_request(self, action: str) -> bool:
        """处理来自 HistoryInput 的补全请求。返回 True 表示已处理。"""
        if not self._matches:
            return False
        if action == "up":
            # 向上移动高亮（循环），不修改输入框内容
            self._completion_index = (self._completion_index - 1) % len(self._matches)
            self._update_hint()
            return True
        elif action == "down":
            # 向下移动高亮（循环），不修改输入框内容
            self._completion_index = (self._completion_index + 1) % len(self._matches)
            self._update_hint()
            return True
        elif action == "tab":
            # 用当前高亮候选填充输入框（加空格便于继续输入参数）
            cmd, _ = self._matches[self._completion_index]
            self.input.load_text(cmd + " ")
            self.input._move_cursor_to_end()
            self._update_hint()
            return True
        elif action == "escape":
            # 关闭补全提示
            self._matches = []
            self._update_hint()
            return True
        return False

    def _update_hint(self) -> None:
        """更新补全提示：列表区 + 统一底部详情区。"""
        hint = self.query_one("#completion-hint", Vertical)
        option_list = self.query_one("#completion-list", OptionList)
        detail_static = self.query_one("#completion-detail", Static)

        if not self._matches:
            option_list.clear_options()
            detail_static.update("")
            hint.remove_class("visible")
            return

        # 列表区：每个候选一条 Option，OptionList 负责高亮与滚动
        options = [
            f"{'▶' if i == self._completion_index else ' '} {cmd:<12} {meta['desc']}"
            for i, (cmd, meta) in enumerate(self._matches)
        ]
        option_list.set_options(options)
        option_list.highlighted = self._completion_index

        self._update_detail()
        hint.add_class("visible")

    def _update_detail(self) -> None:
        """更新底部详情区（用法、说明、操作提示）。"""
        detail_static = self.query_one("#completion-detail", Static)
        if not self._matches:
            detail_static.update("")
            return
        cmd, meta = self._matches[self._completion_index]
        detail_lines = [
            f"用法: {meta['usage']}",
            f"说明: {meta['detail']}",
            f"↑↓ 选择 · Tab 补全 · Esc 关闭 · 共 {len(self._matches)} 条",
        ]
        detail_static.update("\n".join(detail_lines))

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """鼠标点击导致 OptionList 高亮变化时同步内部索引并刷新详情。"""
        if event.option_list.id != "completion-list":
            return
        if event.option_index == self._completion_index:
            return
        self._completion_index = event.option_index
        self._update_detail()

    def on_key(self, event: events.Key) -> None:
        # Ctrl+M 等全局快捷键由 App 处理；这里仅透传
        pass
