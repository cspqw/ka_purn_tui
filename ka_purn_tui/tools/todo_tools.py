# ── 待办/计划工具 ─────────────────────────────────
"""待办工具：update_todo / add_todo_item / complete_todo_item。"""

from __future__ import annotations

from typing import Any

from ..state.novel_state import NovelState
from .registry import ToolDef


def _update_todo(state: NovelState, args: dict[str, Any]) -> str:
    items = args.get("items", [])
    return state.update_todo(items)


def _add_todo_item(state: NovelState, args: dict[str, Any]) -> str:
    return state.add_todo_item(args.get("text", ""))


def _complete_todo_item(state: NovelState, args: dict[str, Any]) -> str:
    return state.complete_todo_item(int(args.get("index", -1)))


TODO_TOOL_DEFS: list[ToolDef] = [
    ToolDef(
        name="update_todo",
        description="整体更新待办/计划列表。items 为对象数组，每项含 text(必填)、done(布尔)、status(pending|active|done)。",
        parameters={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "待办内容"},
                            "done": {"type": "boolean", "description": "是否完成"},
                            "status": {"type": "string", "enum": ["pending", "active", "done"]},
                        },
                        "required": ["text"],
                    },
                }
            },
            "required": ["items"],
        },
        handler=_update_todo,
    ),
    ToolDef(
        name="add_todo_item",
        description="追加单条待办项。",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "待办内容"}},
            "required": ["text"],
        },
        handler=_add_todo_item,
    ),
    ToolDef(
        name="complete_todo_item",
        description="按序号标记待办完成（0-based）。",
        parameters={
            "type": "object",
            "properties": {"index": {"type": "integer", "description": "待办序号（从 0 开始）"}},
            "required": ["index"],
        },
        handler=_complete_todo_item,
    ),
]
