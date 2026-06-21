# ── 文件树面板 ─────────────────────────────────
"""FileTreePanel：用 Textual Tree 控件显示项目文件树，支持点击打开预览。

点击文件节点触发 Tree.NodeSelected 事件，App 层通过 on_tree_node_selected
处理器读取文件内容并切换预览面板到 user 模式。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Tree

from ..state.novel_state import FileNode, NovelState


class FileTreePanel(Vertical):
    """文件树面板（fraction 2）：用 Tree 控件支持点击打开预览。"""

    DEFAULT_CSS = """
    FileTreePanel {
        border: round $primary;
        height: 1fr;
        min-height: 4;
        padding: 0;
    }
    FileTreePanel > Tree {
        height: 1fr;
        border: none;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    """

    title = "文件树"

    def __init__(self) -> None:
        super().__init__()
        self._state: NovelState | None = None

    def compose(self) -> ComposeResult:
        yield Tree("项目根", id="file-tree")

    @property
    def tree(self) -> Tree:
        return self.query_one("#file-tree", Tree)

    def refresh_state(self, state: NovelState) -> None:
        """用最新状态重建文件树。"""
        self._state = state
        if not self.is_mounted or not self.query("#file-tree"):
            self.call_after_refresh(self._rebuild)
            return
        self._rebuild()

    def _rebuild(self) -> None:
        if self._state is None:
            return
        tree = self.tree
        tree.clear()
        if not self._state.file_tree:
            return
        # 设置根节点标签为项目名
        tree.root.set_label(self._state.project_name or "项目根")
        for node in self._state.file_tree:
            self._add_node(tree.root, node)
        tree.root.expand()

    def _add_node(self, parent, node: FileNode) -> None:
        """递归添加节点到 Tree。data 存储相对路径供点击处理使用。"""
        icon = "▸ " if node.is_dir else "· "
        is_current = (not node.is_dir) and (self._state and self._state.current_file == node.path)
        label = f"{icon}{node.name}" + (" ◀" if is_current else "")
        if node.is_dir:
            child = parent.add(label, data=node.path)
            child.expand()
            for c in node.children:
                self._add_node(child, c)
        else:
            parent.add_leaf(label, data=node.path)
