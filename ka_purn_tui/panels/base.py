# ── 右侧面板基类 ─────────────────────────────────
"""BaseRightPanel：右侧面板基类。可滚动，App 在工具执行后调用 refresh_state 刷新内容。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Static

from ..state.novel_state import NovelState


class BaseRightPanel(ScrollableContainer):
    """右侧面板基类：可滚动容器，内部 Static 显示内容。子类实现 render_content。"""

    DEFAULT_CSS = """
    BaseRightPanel {
        border: round $primary;
        padding: 0 1;
        height: 2fr;
        scrollbar-size: 1 1;
    }
    BaseRightPanel > #panel-content {
        height: auto;
        padding: 0;
        border: none;
    }
    """

    title: str = "面板"

    def __init__(self) -> None:
        super().__init__()
        self._state: NovelState | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="panel-content", markup=True)

    @property
    def content(self) -> Static:
        return self.query_one("#panel-content", Static)

    def refresh_state(self, state: NovelState) -> None:
        """App 调用：用最新状态刷新本面板。"""
        self._state = state
        try:
            self.content.update(self.render_content())
        except Exception:
            # compose 尚未完成，延迟刷新
            self.call_after_refresh(self._do_refresh)

    def _do_refresh(self) -> None:
        if self._state is not None:
            try:
                self.content.update(self.render_content())
            except Exception:
                pass

    def render_content(self) -> str:
        """子类实现：返回面板内容（支持 markup）。"""
        return ""
