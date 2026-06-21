# ── 常驻记忆与按需回读工具 ─────────────────────────────────
"""记忆工具：update_character_card / update_world_setting / update_outline /
update_style_guide / read_chapter / read_memory。

前四个用于维护常驻记忆层（Layer 1），这些信息会序列化注入 system prompt，
永久保留，不被上下文裁剪。后两个用于按需回读，避免上下文膨胀。
"""

from __future__ import annotations

from typing import Any

from ..state.novel_state import NovelState
from .registry import ToolDef


# ── 常驻记忆维护工具 ──
def _update_character_card(state: NovelState, args: dict[str, Any]) -> str:
    return state.update_character_card(
        name=args.get("name", ""),
        role=args.get("role", ""),
        traits=args.get("traits", ""),
        appearance=args.get("appearance", ""),
        relations=args.get("relations", ""),
    )


def _update_world_setting(state: NovelState, args: dict[str, Any]) -> str:
    return state.update_world_setting(
        category=args.get("category", ""),
        content=args.get("content", ""),
    )


def _update_outline(state: NovelState, args: dict[str, Any]) -> str:
    return state.update_outline(args.get("chapters", []))


def _update_style_guide(state: NovelState, args: dict[str, Any]) -> str:
    return state.update_style_guide(args.get("text", ""))


# ── 按需回读工具 ──
def _read_chapter(state: NovelState, args: dict[str, Any]) -> str:
    """读取指定章节文件内容（可指定行范围，避免整章回读占用上下文）。"""
    index = int(args.get("index", 0))
    if not (1 <= index <= state.chapter_count):
        return f"章节序号越界: {index}（总 {state.chapter_count} 章）"
    # 推断章节文件名：ch01.md / ch1.md / 第1章.md
    candidates = [
        state.project_root / f"ch{index:02d}.md" if state.project_root else None,
        state.project_root / f"ch{index}.md" if state.project_root else None,
        state.project_root / f"第{index}章.md" if state.project_root else None,
    ]
    path = next((p for p in candidates if p and p.exists()), None)
    if path is None:
        return f"未找到第 {index} 章的文件（尝试过 ch{index:02d}.md / ch{index}.md / 第{index}章.md）"
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"读取失败: {e}"
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    if start_line is not None or end_line is not None:
        lines = content.splitlines(keepends=True)
        s = int(start_line) if start_line is not None else 1
        e = int(end_line) if end_line is not None else len(lines)
        if s < 1 or e > len(lines) or s > e:
            return f"行号越界（文件共 {len(lines)} 行）"
        content = "".join(lines[s - 1 : e])
        return f"第 {index} 章 第 {s}-{e} 行（共 {len(lines)} 行）:\n\n{content}"
    return f"第 {index} 章全文（{len(content)} 字）:\n\n{content}"


def _read_memory(state: NovelState, args: dict[str, Any]) -> str:
    """读取常驻记忆的指定类别。"""
    category = args.get("category", "")
    if category == "characters":
        if not state.characters:
            return "人物卡为空"
        lines = ["【人物卡】"]
        for name, card in state.characters.items():
            lines.append(f"- {name}（{card.get('role', '未设定')}）")
            if card.get("traits"):
                lines.append(f"  性格: {card['traits']}")
            if card.get("appearance"):
                lines.append(f"  外貌: {card['appearance']}")
            if card.get("relations"):
                lines.append(f"  关系: {card['relations']}")
        return "\n".join(lines)
    if category == "world_settings":
        if not state.world_settings:
            return "世界观设定为空"
        lines = ["【世界观设定】"]
        for cat, content in state.world_settings.items():
            lines.append(f"- {cat}: {content}")
        return "\n".join(lines)
    if category == "outline":
        if not state.outline:
            return "大纲为空"
        lines = ["【大纲】"]
        for ch in state.outline:
            lines.append(f"- 第{ch.get('index', '?')}章: {ch.get('summary', '')}")
        return "\n".join(lines)
    if category == "style_guide":
        return state.style_guide or "写作风格说明为空"
    if category == "chapter_summaries":
        if not state.chapter_summaries:
            return "章节摘要为空"
        lines = ["【已完成章节摘要】"]
        for idx in sorted(state.chapter_summaries.keys()):
            lines.append(f"- 第{idx}章: {state.chapter_summaries[idx]}")
        return "\n".join(lines)
    return f"未知类别: {category}（支持: characters/world_settings/outline/style_guide/chapter_summaries）"


MEMORY_TOOL_DEFS: list[ToolDef] = [
    ToolDef(
        name="update_character_card",
        description=(
            "新增或更新人物卡。这些信息会作为常驻记忆永久保留在上下文中，"
            "直接影响后续创作质量，请认真填写完整。空字段不会覆盖已有值。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "人物姓名"},
                "role": {"type": "string", "description": "身份/职业（如：主角/反派/导师）"},
                "traits": {"type": "string", "description": "性格特征"},
                "appearance": {"type": "string", "description": "外貌描写"},
                "relations": {"type": "string", "description": "与其他人物的关系"},
            },
            "required": ["name"],
        },
        handler=_update_character_card,
    ),
    ToolDef(
        name="update_world_setting",
        description=(
            "新增或更新世界观设定。这些信息会作为常驻记忆永久保留在上下文中。"
            "category 如：时间线/地理/势力/规则/历史 等。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "设定类别"},
                "content": {"type": "string", "description": "设定内容"},
            },
            "required": ["category", "content"],
        },
        handler=_update_world_setting,
    ),
    ToolDef(
        name="update_outline",
        description=(
            "整体更新大纲。每章一句话摘要。这些信息会作为常驻记忆永久保留在上下文中。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "chapters": {
                    "type": "array",
                    "description": "各章大纲",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer", "description": "章节序号（1-based）"},
                            "summary": {"type": "string", "description": "该章一句话摘要"},
                        },
                    },
                },
            },
            "required": ["chapters"],
        },
        handler=_update_outline,
    ),
    ToolDef(
        name="update_style_guide",
        description="更新写作风格说明。这些信息会作为常驻记忆永久保留在上下文中。",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "写作风格说明（如：第三人称/多用心理描写/爽文节奏）"},
            },
            "required": ["text"],
        },
        handler=_update_style_guide,
    ),
    ToolDef(
        name="read_chapter",
        description=(
            "读取指定章节文件内容（可指定行范围，避免整章回读占用上下文）。"
            "需要参考前文细节时调用，不要依赖记忆。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "章节序号（1-based）"},
                "start_line": {"type": "integer", "description": "起始行号（可选，从1开始）"},
                "end_line": {"type": "integer", "description": "结束行号（可选，含）"},
            },
            "required": ["index"],
        },
        handler=_read_chapter,
    ),
    ToolDef(
        name="read_memory",
        description=(
            "读取常驻记忆的指定类别。category 可选: "
            "characters(人物卡) / world_settings(世界观) / outline(大纲) / "
            "style_guide(写作风格) / chapter_summaries(已完成章节摘要)。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["characters", "world_settings", "outline", "style_guide", "chapter_summaries"],
                    "description": "要读取的记忆类别",
                },
            },
            "required": ["category"],
        },
        handler=_read_memory,
    ),
]
