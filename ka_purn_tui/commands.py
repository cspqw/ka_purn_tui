# ── 命令注册表 ─────────────────────────────────
"""集中定义所有斜杠命令的元数据，供智能补全与帮助系统使用。

每条命令包含：
  desc:   简短描述（补全列表显示）
  usage:  用法示例
  detail: 详细说明（预选中时显示）
  modes:  适用模式（None 表示所有模式）
"""

from __future__ import annotations

from typing import Any


def _cmd(
    desc: str,
    usage: str,
    detail: str,
    modes: list[str] | None = None,
) -> dict[str, Any]:
    return {"desc": desc, "usage": usage, "detail": detail, "modes": modes}


# 所有命令按字母序排列
COMMAND_REGISTRY: dict[str, dict[str, Any]] = {
    "/chapter": _cmd(
        "跳转章节", "/chapter <n>", "跳转查看小说第 n 章内容", ["novel"]
    ),
    "/clear": _cmd(
        "清空历史", "/clear", "清空当前会话的对话历史（不删除会话本身）"
    ),
    "/delete": _cmd(
        "删除会话", "/delete <id>", "删除指定 ID 的会话（不能删除当前会话）"
    ),
    "/effort": _cmd(
        "思考强度", "/effort high|max", "设置思考强度：high 或 max"
    ),
    "/follow": _cmd(
        "预览跟随", "/follow on|off", "开关小说文件预览的自动跟随功能", ["novel"]
    ),
    "/help": _cmd(
        "查看帮助", "/help", "显示当前模式的命令帮助"
    ),
    "/info": _cmd(
        "会话信息", "/info", "显示当前会话、模型、上下文占用等信息"
    ),
    "/load": _cmd(
        "载入会话/文件", "/load <id|file>", "载入历史会话（传 ID）或加载文件到上下文（传路径）"
    ),
    "/ls": _cmd(
        "历史会话", "/ls", "弹出模态屏选择/载入历史会话（同 /sessions）"
    ),
    "/model": _cmd(
        "切换模型", "/model <name>", "切换 DeepSeek 模型"
    ),
    "/mode": _cmd(
        "切换模式", "/mode chat|novel", "切换到聊天或小说创作模式"
    ),
    "/new": _cmd(
        "新建会话", "/new [名称]", "创建新的对话会话，可选指定名称"
    ),
    "/novel": _cmd(
        "小说项目", "/novel new|file|open <...>", "新建/打开小说项目", ["novel"]
    ),
    "/panel": _cmd(
        "面板控制", "/panel ratio <n>", "调整左右分栏比例", ["novel"]
    ),
    "/plan": _cmd(
        "计划模式", "/plan <请求>", "模型先制定计划到 .Project/，确认后执行", ["novel"]
    ),
    "/preset": _cmd(
        "预设管理", "/preset list|use|add|del|show", "管理角色预设"
    ),
    "/quit": _cmd(
        "退出", "/quit", "退出 K.A-purn-tui"
    ),
    "/rename": _cmd(
        "重命名会话", "/rename <名称>", "重命名当前会话"
    ),
    "/sessions": _cmd(
        "历史会话", "/sessions", "弹出模态屏选择/载入历史会话"
    ),
    "/system": _cmd(
        "系统提示词", "/system <prompt>", "设置当前模式的系统提示词"
    ),
    "/think": _cmd(
        "思考开关", "/think on|off", "开关 DeepSeek 思考模式"
    ),
}


def match_commands(prefix: str, mode: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    """返回与 prefix 匹配的命令列表（前缀匹配）。

    Args:
        prefix: 用户输入的命令前缀（如 "/n"）
        mode: 当前模式名，用于过滤模式专属命令；None 不过滤

    Returns:
        [(command, meta), ...] 按字母序排列
    """
    if not prefix.startswith("/"):
        return []
    results = []
    for cmd, meta in COMMAND_REGISTRY.items():
        if not cmd.startswith(prefix) and not prefix.startswith(cmd):
            # 前缀匹配：命令以 prefix 开头
            if not cmd.startswith(prefix):
                continue
        if cmd.startswith(prefix):
            # 模式过滤
            cmd_modes = meta.get("modes")
            if mode and cmd_modes and mode not in cmd_modes:
                continue
            results.append((cmd, meta))
    return sorted(results, key=lambda x: x[0])
