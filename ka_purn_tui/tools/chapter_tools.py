# ── 章节工具 ─────────────────────────────────
"""章节工具：set_chapter_count / set_current_chapter / mark_chapter_done。"""

from __future__ import annotations

from typing import Any

from ..state.novel_state import NovelState
from .registry import ToolDef


def _set_chapter_count(state: NovelState, args: dict[str, Any]) -> str:
    return state.set_chapter_count(int(args.get("count", 0)))


def _set_current_chapter(state: NovelState, args: dict[str, Any]) -> str:
    return state.set_current_chapter(int(args.get("index", 0)), args.get("title", ""))


def _mark_chapter_done(state: NovelState, args: dict[str, Any]) -> str:
    return state.mark_chapter_done(int(args.get("index", 0)))


def _set_progress(state: NovelState, args: dict[str, Any]) -> str:
    return state.set_progress(
        int(args.get("current", 0)),
        int(args.get("total", 0)),
        args.get("label", ""),
    )


CHAPTER_TOOL_DEFS: list[ToolDef] = [
    ToolDef(
        name="set_chapter_count",
        description="设定小说总章数。开始创作时调用。",
        parameters={
            "type": "object",
            "properties": {"count": {"type": "integer", "description": "总章数"}},
            "required": ["count"],
        },
        handler=_set_chapter_count,
    ),
    ToolDef(
        name="set_current_chapter",
        description="声明正在写第几章。每次切换章节时调用，右侧面板会高亮当前章。",
        parameters={
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "章节序号（1-based）"},
                "title": {"type": "string", "description": "章节标题"},
            },
            "required": ["index"],
        },
        handler=_set_current_chapter,
    ),
    ToolDef(
        name="mark_chapter_done",
        description="标记某章完成。",
        parameters={
            "type": "object",
            "properties": {"index": {"type": "integer", "description": "章节序号（1-based）"}},
            "required": ["index"],
        },
        handler=_mark_chapter_done,
    ),
    ToolDef(
        name="set_progress",
        description="更新顶栏自定义进度条。current=当前进度数 total=总数 label=可选标签（如'第4章填充中'）。写章节或执行任务时勤更新，用户会盯着进度条看。",
        parameters={
            "type": "object",
            "properties": {
                "current": {"type": "integer", "description": "当前进度值"},
                "total": {"type": "integer", "description": "总数"},
                "label": {"type": "string", "description": "进度标签（如'第4章填充中'）", "default": ""},
            },
            "required": ["current", "total"],
        },
        handler=_set_progress,
    ),
]
