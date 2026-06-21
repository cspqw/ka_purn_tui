# ── 模式系统基类 ─────────────────────────────────
"""Mode 抽象基类：定义该模式下的 system prompt、可用工具、右侧面板、命令。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.widget import Widget


class Mode(ABC):
    """模式基类。App 持有 current_mode，切换时 recompose 右侧容器并重建工具集。"""

    name: str = ""
    display_name: str = ""

    @abstractmethod
    def get_system_prompt(self) -> str:
        """返回该模式的 system prompt。"""
        ...

    @abstractmethod
    def get_tools(self) -> list[dict]:
        """返回 OpenAI tools schema 列表（可为空）。"""
        ...

    @abstractmethod
    def get_right_panels(self) -> list[type[Widget]]:
        """返回该模式右侧要显示的面板 widget 类列表（可为空）。"""
        ...

    def get_help(self) -> str:
        """该模式下的帮助文本。"""
        return ""
