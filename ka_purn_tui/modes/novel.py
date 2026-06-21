# ── 小说创作模式 ─────────────────────────────────
"""NovelMode：小说创作模式。模型通过 tool call 操作章节/待办/文件，右侧实时追踪。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..config import DEFAULT_NOVEL_SYSTEM_PROMPT
from ..tools.executor import novel_tool_schemas
from .base import Mode

if TYPE_CHECKING:
    from textual.widget import Widget


class NovelMode(Mode):
    """小说创作模式。"""

    name = "novel"
    display_name = "小说创作"

    def __init__(self, system_prompt: str | None = None) -> None:
        # 允许通过 config.json 的 novel.system_prompt 覆盖默认提示词
        self._system_prompt: str = system_prompt if system_prompt else DEFAULT_NOVEL_SYSTEM_PROMPT

    def get_system_prompt(self) -> str:
        return self._system_prompt

    def get_tools(self) -> list[dict]:
        # 合并三类工具的 OpenAI schema
        return novel_tool_schemas()

    def get_right_panels(self) -> list[type[Widget]]:
        # 延迟导入避免循环依赖
        from ..panels.chapter_panel import ChapterPanel
        from ..panels.file_preview_panel import FilePreviewPanel
        from ..panels.side_panels import SidePanels

        return [ChapterPanel, SidePanels, FilePreviewPanel]

    def get_help(self) -> str:
        return (
            "小说创作模式命令:\n"
            "  /mode chat           切换回聊天模式\n"
            "  /new [名称]          新建会话\n"
            "  /sessions            选择/载入历史会话（模态屏）\n"
            "  /load <id>           载入指定会话\n"
            "  /rename <名称>       重命名当前会话\n"
            "  /delete <id>         删除指定会话\n"
            "  /novel new <name>    新建小说项目（文件夹）\n"
            "  /novel open <path>   打开已有小说项目\n"
            "  /plan <请求>          计划模式：模型先制定计划，确认后执行\n"
            "  /chapter <n>         跳转查看第 n 章\n"
            "  /follow on|off       开关文件预览自动跟随\n"
            "  /panel ratio <n>     调整左右分栏比例\n"
            "  /special [内容]      设置/查看特殊系统提示词（全局前置）\n"
            "通用命令: /think /effort /model /load /clear /info /quit\n"
            "快捷键: Ctrl+R 切换右侧面板 | Ctrl+C 停止推理/退出 | Enter 提交 | Shift+Enter 换行\n"
            "文件树: 点击文件节点可在预览面板查看内容（无行数限制）\n"
            "输入 / 后按 Tab 智能补全命令 | ↑↓ 翻阅历史输入\n"
            "复制文本: 按住 Shift 用鼠标选择，再 Ctrl+Shift+C 复制\n"
            "上下文管理: 自动精简旧 tool result（60%）/ 摘要早期对话（80%）/ 强制截断（90%）\n"
            "常驻记忆: 模型可调用 update_character_card / update_world_setting / update_outline / update_style_guide\n"
            "按需回读: 模型可调用 read_chapter / read_memory 参考前文"
        )
