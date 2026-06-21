# ── 聊天模式 ─────────────────────────────────
"""ChatMode：迁移现有聊天功能（预设/思考/加载文件）。无工具，无右侧面板。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..config import DEFAULT_PRESETS
from .base import Mode

if TYPE_CHECKING:
    from textual.widget import Widget


class ChatMode(Mode):
    """聊天模式：保持原有 CLI 体验。"""

    name = "chat"
    display_name = "聊天"

    def __init__(self) -> None:
        self.presets: dict[str, str] = DEFAULT_PRESETS.copy()
        self.current_preset: str = "default"

    def get_system_prompt(self) -> str:
        return self.presets.get(self.current_preset, DEFAULT_PRESETS["default"])

    def get_tools(self) -> list[dict]:
        return []

    def get_right_panels(self) -> list[type[Widget]]:
        # chat 模式默认隐藏右侧面板
        return []

    def get_help(self) -> str:
        return (
            "聊天模式命令:\n"
            "  /mode novel          切换到小说创作模式\n"
            "  /new [名称]          新建会话\n"
            "  /sessions            选择/载入历史会话（模态屏）\n"
            "  /load <id>           载入指定会话（id 见 /sessions）\n"
            "  /rename <名称>       重命名当前会话\n"
            "  /delete <id>         删除指定会话\n"
            "  /preset list|use|add|del|show  预设管理\n"
            "  /think on|off        开关思考模式\n"
            "  /effort high|max     设置思考强度\n"
            "  /model <name>        切换模型\n"
            "  /load <file>         加载文件到上下文\n"
            "  /system <prompt>     设置系统提示词\n"
            "  /clear               清空当前会话历史\n"
            "  /info                显示会话信息\n"
            "  /quit                退出\n"
            "快捷键: Ctrl+R 右侧面板 | Ctrl+C 停止推理/退出 | Enter 提交 | Shift+Enter 换行\n"
            "输入 / 后按 Tab 智能补全命令 | ↑↓ 翻阅历史输入\n"
            "复制文本: 按住 Shift 用鼠标选择，再 Ctrl+Shift+C 复制"
        )
