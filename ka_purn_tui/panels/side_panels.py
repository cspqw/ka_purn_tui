# ── 左右并排面板容器 ─────────────────────────────────
"""SidePanels：将 TodoPanel 和 FileTreePanel 左右并排，总高度 2fr。"""

from __future__ import annotations

from textual.containers import Horizontal
from textual.widget import Widget

from ..state.novel_state import NovelState


class SidePanels(Horizontal):
    """水平容器：左侧待办，右侧文件树，总高度 2fr。"""

    DEFAULT_CSS = """
    SidePanels {
        height: 3fr;
        min-height: 4;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        from .todo_panel import TodoPanel
        from .file_tree_panel import FileTreePanel

        self._todo = TodoPanel()
        self._tree = FileTreePanel()

    def compose(self):
        yield self._todo
        yield self._tree

    def refresh_state(self, state: NovelState) -> None:
        self._todo.refresh_state(state)
        self._tree.refresh_state(state)
