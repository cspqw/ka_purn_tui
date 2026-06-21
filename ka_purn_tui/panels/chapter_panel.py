# ── 章节进度面板 ─────────────────────────────────
"""ChapterPanel：显示总章数、当前章节高亮、完成进度条。"""

from __future__ import annotations

from .base import BaseRightPanel


class ChapterPanel(BaseRightPanel):
    """章节进度面板（fraction 1，紧凑）。"""

    DEFAULT_CSS = """
    ChapterPanel {
        border: round $accent;
        height: 1fr;
        min-height: 3;
    }
    """

    title = "章节进度"

    def render_content(self) -> str:
        if self._state is None or self._state.chapter_count == 0:
            return "[dim]尚未设定章节数[/dim]"
        s = self._state
        # 优先使用模型报告的自定义进度，否则回退到 done_chapter_count
        pg_current = s.progress_current if s.progress_total > 0 else s.done_chapter_count
        pg_total = s.progress_total if s.progress_total > 0 else s.chapter_count
        pct = (pg_current / pg_total * 100) if pg_total > 0 else 0
        # 进度条（20 格）
        bar_len = 20
        filled = int(bar_len * pct / 100)
        bar = "▓" * filled + "░" * (bar_len - filled)
        cur = s.current_chapter
        label = s.progress_label if s.progress_label else (f"第 {cur} 章填充中" if cur else "空闲")
        lines = [f"[bold]{label}[/bold]  [cyan]{pg_current}/{pg_total}[/cyan]  {pct:.0f}%", f"[{bar}]"]
        # 章节列表（最多显示前 12 章，避免溢出）
        for c in s.chapters[:12]:
            if c.done:
                mark = "[green]√[/green]"
            elif c.index == cur:
                mark = "[yellow]▶[/yellow]"
            else:
                mark = "[dim]☐[/dim]"
            lines.append(f"{mark} 第{c.index}章 {c.title}")
        if len(s.chapters) > 12:
            lines.append(f"[dim]... 共 {len(s.chapters)} 章[/dim]")
        return "\n".join(lines)
