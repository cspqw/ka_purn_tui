# ── 工具执行器 ─────────────────────────────────
"""ToolExecutor：分发 tool_call → 执行 handler → 返回结果字符串。

执行后由调用方（App worker）负责刷新 UI 面板与回传工具结果给模型。
"""

from __future__ import annotations

import json
from typing import Any

from ..state.novel_state import NovelState
from .chapter_tools import CHAPTER_TOOL_DEFS
from .file_tools import FILE_TOOL_DEFS
from .memory_tools import MEMORY_TOOL_DEFS
from .registry import ToolRegistry
from .todo_tools import TODO_TOOL_DEFS


def build_novel_registry() -> ToolRegistry:
    """构建小说模式工具注册表。"""
    reg = ToolRegistry()
    reg.register_all(TODO_TOOL_DEFS)
    reg.register_all(CHAPTER_TOOL_DEFS)
    reg.register_all(FILE_TOOL_DEFS)
    reg.register_all(MEMORY_TOOL_DEFS)
    return reg


def novel_tool_schemas() -> list[dict[str, Any]]:
    """返回小说模式全部工具的 OpenAI schema。"""
    return build_novel_registry().schemas()


class ToolExecutor:
    """工具执行器。"""

    def __init__(self, registry: ToolRegistry, state: NovelState) -> None:
        self.registry = registry
        self.state = state

    def dispatch(self, name: str, args_json: str) -> str:
        """执行工具调用，返回结果字符串（错误也以字符串返回给模型）。"""
        tool = self.registry.get(name)
        if tool is None:
            return f"未知工具: {name}"
        try:
            args = json.loads(args_json) if args_json.strip() else {}
        except json.JSONDecodeError as e:
            return f"参数解析失败: {e}（原始: {args_json[:200]}）"
        try:
            return tool.handler(self.state, args)
        except Exception as e:  # noqa: BLE001
            return f"工具执行出错 {name}: {type(e).__name__}: {e}"

    def summary(self, name: str, args_json: str) -> str:
        """生成工具调用的简短摘要（供左侧聊天区显示）。"""
        try:
            args = json.loads(args_json) if args_json.strip() else {}
        except json.JSONDecodeError:
            args = {}
        if name == "append_to_file":
            path = args.get("path", "?")
            n = len(args.get("text", ""))
            return f"append_to_file({path}, +{n}字)"
        if name in ("write_file", "create_novel_file"):
            path = args.get("path", "?")
            n = len(args.get("content", ""))
            return f"{name}({path}, {n}字)"
        if name == "create_novel_folder":
            return f"create_novel_folder({args.get('path', '?')})"
        if name == "edit_file":
            mode = args.get("mode", "?")
            path = args.get("path", "?")
            return f"edit_file({path}, {mode})"
        if name == "set_chapter_count":
            return f"set_chapter_count({args.get('count', '?')})"
        if name == "set_current_chapter":
            return f"set_current_chapter({args.get('index', '?')}, {args.get('title', '')})"
        if name == "mark_chapter_done":
            return f"mark_chapter_done({args.get('index', '?')})"
        if name == "update_todo":
            return f"update_todo({len(args.get('items', []))}项)"
        if name == "add_todo_item":
            return f"add_todo_item({args.get('text', '')[:20]})"
        if name == "complete_todo_item":
            return f"complete_todo_item({args.get('index', '?')})"
        if name == "update_character_card":
            return f"update_character_card({args.get('name', '?')})"
        if name == "update_world_setting":
            return f"update_world_setting({args.get('category', '?')})"
        if name == "update_outline":
            return f"update_outline({len(args.get('chapters', []))}章)"
        if name == "update_style_guide":
            return f"update_style_guide({len(args.get('text', ''))}字)"
        if name == "read_chapter":
            return f"read_chapter({args.get('index', '?')})"
        if name == "read_memory":
            return f"read_memory({args.get('category', '?')})"
        return f"{name}({args})"
