# ── 待办/计划面板 ─────────────────────────────────
"""TodoPanel：显示待办列表，活跃项黄色高亮 + 自动滚动跟随。"""

from __future__ import annotations

from ..state.novel_state import NovelState
from .base import BaseRightPanel


class TodoPanel(BaseRightPanel):
    """待办面板（fraction 2）。活跃待办自动滚动到可视范围。"""

    DEFAULT_CSS = """
    TodoPanel {
        border: round $success;
        height: 1fr;
        min-height: 4;
    }
    """

    title = "待办/计划"

    def render_content(self) -> str:
        if self._state is None or not self._state.todos:
            return "[dim]暂无待办[/dim]"
        lines = []
        for i, t in enumerate(self._state.todos):
            text = t.text if len(t.text) <= 40 else t.text[:38] + ".."
            if t.done or t.status == "done":
                lines.append(f"[green]√[/green] [dim]{text}[/dim]")
            elif t.status == "active":
                lines.append(f"[yellow]▸[/yellow] [bold yellow on #333300]{text}[/bold yellow on #333300]")
            else:
                lines.append(f"[dim]○[/dim] {text}")
        return "\n".join(lines)

    def refresh_state(self, state: NovelState) -> None:
        """刷新内容后自动滚动到活跃待办。"""
        super().refresh_state(state)
        self.call_after_refresh(self._scroll_to_active)

    def _scroll_to_active(self) -> None:
        """找到活跃待办行号，自动滚动使其可见。"""
        if self._state is None:
            return
        for i, t in enumerate(self._state.todos):
            if t.status == "active" and not (t.done or t.status == "done"):
                # 滚动使活跃待办上方留 2 行上下文
                self.scroll_to(y=max(0, i - 2), animate=False)
                return
