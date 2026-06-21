# ── 工具注册表 ─────────────────────────────────
"""ToolDef：工具定义（schema + handler）。executor 据此分发调用。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..state.novel_state import NovelState

# 工具处理函数签名：(state, args_dict) -> 结果字符串
ToolHandler = Callable[[NovelState, dict[str, Any]], str]


@dataclass
class ToolDef:
    """单个工具定义。"""

    name: str
    description: str
    parameters: dict[str, Any]            # JSON Schema
    handler: ToolHandler = field(repr=False)

    def to_openai_schema(self) -> dict[str, Any]:
        """转 OpenAI tools 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """工具注册表：name -> ToolDef。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def register_all(self, tools: list[ToolDef]) -> None:
        for t in tools:
            self.register(t)

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())
