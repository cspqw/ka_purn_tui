# ── 左侧聊天消息流 ─────────────────────────────────
"""ChatView：基于 RichLog 的滚动消息流，展示用户/思考/回答/工具调用。

流式输出时使用行缓冲：按 \\n 分行累积，避免每个碎片 chunk 占一行
（RichLog 每次 write 都换行，若每个小 chunk 单独 write 会变成每字一行）。
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import RichLog

# 缓冲超过此长度时强制 flush（即使没有换行符），保证长文本实时性
DEFAULT_FLUSH_THRESHOLD = 80


class ChatView(RichLog):
    """聊天消息流。"""

    DEFAULT_CSS = """
    ChatView {
        border: round $primary;
        background: $surface;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    ChatView:focus { border: round $accent; }
    """

    def __init__(self, flush_threshold: int | None = None, **kwargs: Any) -> None:
        super().__init__(highlight=False, markup=True, auto_scroll=True, wrap=True, **kwargs)
        self._think_buf: str = ""
        self._answer_buf: str = ""
        # 允许通过 config.json 的 ui.flush_threshold 覆盖默认值
        self._flush_threshold: int = (
            flush_threshold if flush_threshold is not None else DEFAULT_FLUSH_THRESHOLD
        )

    # ── 行缓冲核心 ──
    def _append_buf(self, text: str, buf_name: str, style: str) -> None:
        """追加文本到缓冲，按换行符分行写出，剩余留缓冲。"""
        buf = self._think_buf if buf_name == "think" else self._answer_buf
        buf += text
        # 按换行符分割：完整行立即写出，最后一段留缓冲
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            if line:
                self.write(Text(line, style=style))
            else:
                self.write(Text(""))
        # 缓冲过长时强制写出，保证实时性
        if len(buf) >= self._flush_threshold:
            self.write(Text(buf, style=style))
            buf = ""
        if buf_name == "think":
            self._think_buf = buf
        else:
            self._answer_buf = buf

    def _flush_buf(self, buf_name: str, style: str) -> None:
        """写出缓冲区剩余内容。"""
        if buf_name == "think":
            if self._think_buf:
                self.write(Text(self._think_buf, style=style))
                self._think_buf = ""
        else:
            if self._answer_buf:
                self.write(Text(self._answer_buf, style=style))
                self._answer_buf = ""

    # ── 各类消息写入 ──
    def write_user(self, text: str) -> None:
        self.write(Text(f"你> {text}", style="bold green"))

    def write_thinking(self, text: str) -> None:
        # 思考内容灰色斜体，行缓冲后写入
        self._append_buf(text, "think", "dim italic")

    def write_thinking_start(self) -> None:
        self.write(Text("┌─ 思考过程 " + "─" * 40, style="yellow"))

    def write_thinking_end(self) -> None:
        self._flush_buf("think", "dim italic")
        self.write(Text("└" + "─" * 52, style="yellow"))

    def write_answer_start(self) -> None:
        self.write(Text("─" * 20 + " 回答 " + "─" * 20, style="bold"))

    def write_answer(self, text: str) -> None:
        self._append_buf(text, "answer", "white")

    def write_tool_call(self, summary: str) -> None:
        """工具调用摘要（折叠为单行）。"""
        # 工具调用前先 flush 思考与回答缓冲，避免顺序错乱或工具调用嵌在思考块里
        self._flush_buf("think", "dim italic")
        self._flush_buf("answer", "white")
        self.write(Text(f"◆ {summary}", style="cyan"))

    def write_tool_calling(self, tool_name: str) -> None:
        """工具开始调用（实时提示，参数流式接收中）。"""
        self._flush_buf("think", "dim italic")
        self._flush_buf("answer", "white")
        self.write(Text(f"→ 正在调用 {tool_name}", style="yellow"))

    def write_info(self, text: str) -> None:
        self._flush_buf("answer", "white")
        self.write(Text(text, style="cyan"))

    def write_warn(self, text: str) -> None:
        self._flush_buf("answer", "white")
        self.write(Text(text, style="yellow"))

    def write_error(self, text: str) -> None:
        self._flush_buf("answer", "white")
        self.write(Text(text, style="red"))

    def write_separator(self) -> None:
        # 分隔前 flush 所有缓冲
        self._flush_buf("think", "dim italic")
        self._flush_buf("answer", "white")
        self.write(Text(""))
