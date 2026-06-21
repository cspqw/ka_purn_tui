# ── 配置加载与持久化 ─────────────────────────────────
"""配置加载与保存。迁移自原 DeepSeekChat._load_config/_save_config，扩展模式与小说项目字段。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# 配置文件路径（使用 .jsonc 以支持注释，同时兼容旧版 .json）
CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.jsonc"
if not CONFIG_FILE.exists():
    CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"
# 会话存储文件路径（多会话持久化，与 config.json 解耦）
SESSIONS_FILE = Path(__file__).resolve().parent.parent / "sessions.json"

# 可用模型列表
AVAILABLE_MODELS: dict[str, str] = {
    "deepseek-v4-flash": "推荐，性价比高 (284B参数, 1M上下文)",
    "deepseek-v4-pro": "旗舰，最强推理 (1.6T参数, 1M上下文)",
    "deepseek-chat": "Legacy → v4-flash，7月24日退役",
    "deepseek-reasoner": "Legacy → v4-flash thinking，7月24日退役",
}

# 默认系统提示词预设
DEFAULT_PRESETS: dict[str, str] = {
    "default": "你是一个有帮助的助手，请用中文回答。",
    "code": "你是一个专业的程序员助手，擅长编写高质量代码。请用中文回答。",
    "writer": "你是一个专业的写作助手，擅长创作各类文本。请用中文回答。",
    "analyst": "你是一个专业的数据分析师，擅长数据解读和洞察提取。请用中文回答。",
}

# 小说模式默认系统提示词（可被 config.json 中的 novel.system_prompt 覆盖）
DEFAULT_NOVEL_SYSTEM_PROMPT: str = """你是一个专业的小说创作助手，正在与用户协作创作小说。请用中文。

你可以调用以下工具来推进创作，**主动**使用它们让用户能在右侧面板实时追踪进度：

【章节管理】
- set_chapter_count(count): 设定小说总章数（开始创作时调用）
- set_current_chapter(index, title): 声明你正在写第几章（每次切换章节时调用）
- mark_chapter_done(index): 完成某章后标记

【待办/计划】
- update_todo(items): 整体更新待办列表（含大纲、设定、各章节等任务）
- add_todo_item(text): 追加单条待办
- complete_todo_item(index): 标记某条待办完成
- 注意：待办名称（text 字段）禁止使用任何表情符号（emoji），一律使用纯文本

【文件操作】（路径相对于当前小说项目根目录）
- create_novel_folder(path): 新建文件夹（如按卷分目录）
- create_novel_file(path, content): 新建章节文件
- write_file(path, content): 覆盖写文件
- append_to_file(path, text): 追加内容到文件（**写章节正文时多次调用，用户能实时看到内容增长**）
- delete_file(path): 将文件移至 .pr/pre-delete/ 预删除区域（不会立即删除，你仍可读取）
- read_file(path, max_chars): 读取任意文件内容（含 .pr/pre-delete/ 下的预删除文件）

【常驻记忆维护】（这些信息会作为常驻记忆永久保留在上下文中，直接影响后续创作质量，请认真填写完整）
- update_character_card(name, role, traits, appearance, relations): 新增或更新人物卡
- update_world_setting(category, content): 新增或更新世界观设定
- update_outline(chapters): 整体更新大纲（每章一句话摘要）
- update_style_guide(text): 更新写作风格说明

【按需回读】（需要参考已完成章节或设定时调用，避免上下文膨胀）
- read_chapter(index, start_line, end_line): 读取指定章节文件内容（可指定行范围）
- read_memory(category): 读取常驻记忆（characters/world_settings/outline/style_guide/chapter_summaries）

创作规范：
1. 开始前先 set_chapter_count 设定总章数，并 update_todo 列出创作计划
2. 写每一章前先 set_current_chapter，让用户知道你在写哪章
3. 章节正文用 append_to_file 分段追加（每段几百字），不要一次性 write_file 全部内容，这样用户能实时看到文字增长
4. 每章写完调用 mark_chapter_done 并 complete_todo_item 更新进度
5. 文件用 .md 格式，章节文件命名如 ch01.md、ch02.md
6. 确定人物/世界观/大纲后，主动调用常驻记忆工具保存，后续创作会自动注入这些信息
7. 需要参考前文细节时，用 read_chapter 按需读取，不要依赖记忆
8. delete_file 删除的文件会进入 .pr/pre-delete/ 预删除区，你仍可通过 read_file('.pr/pre-delete/文件名') 读取；用户回复"确认删除"后才会真正移除

项目结构规范：
- 小说内容文件（章节正文 .md）直接放在项目根目录，如 ch01.md、ch02.md
- 工程文件（大纲、计划、设定等）放在 .Project/ 文件夹下
- .pr/pre-delete/ 是预删除区域，delete_file 的文件暂存于此，用户确认后才移至回收站
- 不要手动修改 .Project/ 内的文件，它们由系统自动管理
"""

# 章节摘要专用系统提示词（mark_chapter_done 时后台调用，不走主对话流）
CHAPTER_SUMMARY_SYSTEM_PROMPT: str = """你是一个专业的小说章节摘要助手。请用中文。

任务：为给定章节生成一段 200-400 字的摘要，供后续创作参考。

摘要必须包含：
1. 核心情节：本章发生了什么关键事件
2. 人物动态：主要角色的行动、决策、情感变化
3. 重要对话：影响剧情走向的关键对话要点（不要逐字记录）
4. 伏笔与线索：埋下的伏笔、揭示的线索、未解之谜
5. 章节结尾状态：本章结束时各角色的处境与位置

要求：
- 用流畅的叙述体，不要分点列表
- 客观陈述，不要评价文笔
- 保留所有人名、地名、专有名词
- 控制在 200-400 字
- 只输出摘要正文，不要任何前缀说明
"""

# 早期对话摘要专用系统提示词（上下文压缩时后台调用，不走主对话流）
DIALOGUE_SUMMARY_SYSTEM_PROMPT: str = """你是一个对话压缩助手，专门为小说创作场景服务。请用中文。

任务：把早期的创作对话历史压缩成一段结构化摘要，供模型继续创作时参考。

摘要必须保留：
1. 用户指令：用户对剧情、人物、风格的具体要求
2. 创作决策：已确定的人物设定、世界观、大纲走向
3. 已完成工作：哪些章节已写、哪些待办已完成
4. 当前任务：正在进行的章节和未完成的事项
5. 用户偏好：用户表达过的喜好（如"少用对话""多写心理"）

要求：
- 按主题分段，用【用户指令】【创作决策】【已完成】【当前任务】【用户偏好】作为小标题
- 每个主题下用简洁的要点，不要逐条复述对话
- 保留所有专有名词和关键数字（章节号、字数等）
- 总长度控制在 500-800 字
- 只输出摘要正文，不要任何前缀说明
"""

# 运行时默认配置（api_key 仅从环境变量读取，不再硬编码）
DEFAULT_CONFIG: dict[str, Any] = {
    "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-pro",
    "reasoning_effort": "high",
    "thinking_enabled": True,
    "max_tokens": 16_384,
    "temperature": 0.7,
    "stream": True,
    # ── API 行为配置 ──
    "api": {
        # 流式请求遇到 RemoteProtocolError 等网络断流时的最大重试次数
        "stream_max_retries": 1,
    },
    # 特殊系统提示词：会插入到所有 system prompt 最前面（含主对话/章节摘要/对话摘要），后接换行
    "special_system_prompt": "",
    # 新增字段
    "current_mode": "chat",
    "novel_projects": {},  # {name: root_path}
    # 当前会话 ID（多会话管理）
    "current_session_id": "",
    # 输入历史（上/下键翻阅，跨会话保留）
    "input_history": [],
    # ── UI 布局配置 ──
    "ui": {
        # 窗口缩放阈值（列数）：低于 width_narrow 为窄布局，高于 width_wide 为宽布局
        "width_narrow": 100,
        "width_wide": 160,
        # 缩放防抖滞回余量（列数），避免边界来回跳
        "width_hysteresis": 5,
        # ChatView 行缓冲强制 flush 长度（字符数），保证长文本实时性
        "flush_threshold": 80,
    },
    # ── Agent 回路配置 ──
    "agent": {
        # agent 回路最大轮数（防止工具调用死循环）
        "max_rounds": 12,
    },
    # ── 小说模式配置 ──
    "novel": {
        # 小说模式系统提示词
        "system_prompt": DEFAULT_NOVEL_SYSTEM_PROMPT,
    },
    # ── 上下文管理配置 ──
    "context": {
        # 模型上下文窗口大小（tokens），DeepSeek 统一 1M
        "max_tokens": 1_000_000,
        # 水位线（占 max_tokens 的比例，0-1）
        "warn_threshold": 0.6,        # 警戒：精简旧 tool result
        "compress_threshold": 0.8,    # 压缩：摘要早期对话
        "critical_threshold": 0.9,    # 紧急：强制截断
        # 滑动窗口：保留最近 N 轮（user→assistant→tool 算一轮）原文
        "sliding_window_rounds": 6,
        # 章节摘要最大字符数
        "chapter_summary_max_chars": 400,
        # 是否在 mark_chapter_done 时自动生成章节摘要
        "auto_summarize_on_chapter_done": False,
        # 是否在警戒水位自动精简 tool result
        "auto_compact_tool_results": True,
    },
}


def _strip_json_comments(text: str) -> str:
    """去掉 JSON 文本中的 // 行内注释，保留字符串内部的 //。

    仅处理双引号字符串外的 // 注释，从 // 开始到行尾的内容会被移除。
    """
    result: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            result.append(ch)
        else:
            if ch == '"':
                in_string = True
                result.append(ch)
            elif ch == "/" and i + 1 < n and text[i + 1] == "/":
                # 跳过到行尾，保留换行符以保持行号
                while i < n and text[i] != "\n":
                    i += 1
                if i < n:
                    result.append(text[i])
            else:
                result.append(ch)
        i += 1
    return "".join(result)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并：override 中的同名键覆盖 base，dict 类型继续递归合并。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> dict[str, Any]:
    """加载持久化配置，与默认配置深度合并。"""
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                saved = json.loads(_strip_json_comments(f.read()))
            cfg = _deep_merge(DEFAULT_CONFIG, saved)
        except Exception:
            pass
    # 确保关键字段存在
    cfg.setdefault("presets", DEFAULT_PRESETS.copy())
    cfg.setdefault("current_preset", "default")
    cfg.setdefault("history", [])
    cfg.setdefault("current_mode", "chat")
    cfg.setdefault("novel_projects", {})
    cfg.setdefault("current_session_id", "")
    cfg.setdefault("special_system_prompt", "")
    # 确保嵌套配置组存在（即使 config.json 缺失某组也能用默认值）
    cfg.setdefault("ui", {})
    cfg["ui"].setdefault("width_narrow", DEFAULT_CONFIG["ui"]["width_narrow"])
    cfg["ui"].setdefault("width_wide", DEFAULT_CONFIG["ui"]["width_wide"])
    cfg["ui"].setdefault("width_hysteresis", DEFAULT_CONFIG["ui"]["width_hysteresis"])
    cfg["ui"].setdefault("flush_threshold", DEFAULT_CONFIG["ui"]["flush_threshold"])
    cfg.setdefault("agent", {})
    cfg["agent"].setdefault("max_rounds", DEFAULT_CONFIG["agent"]["max_rounds"])
    cfg.setdefault("api", {})
    cfg["api"].setdefault("stream_max_retries", DEFAULT_CONFIG["api"]["stream_max_retries"])
    cfg.setdefault("novel", {})
    cfg["novel"].setdefault("system_prompt", DEFAULT_CONFIG["novel"]["system_prompt"])
    cfg.setdefault("context", {})
    for k, v in DEFAULT_CONFIG["context"].items():
        cfg["context"].setdefault(k, v)
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    """保存配置到文件。"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def apply_special_prompt(config: dict[str, Any], base_prompt: str) -> str:
    """在 base_prompt 前插入特殊系统提示词（若配置了）。

    用于所有 system prompt 构造点：主对话、章节摘要、对话摘要、/system、/preset use。
    插入格式：{special}\\n{base_prompt}。
    """
    special = config.get("special_system_prompt", "") if config else ""
    if special:
        return special + "\n" + base_prompt
    return base_prompt


def get_project_sessions_path(project_root: Path) -> Path:
    """返回项目级 sessions.json 路径：{project_root}/.Project/sessions.json。"""
    return project_root / ".Project" / "sessions.json"


# ── DeepSeek V3 官方 tokenizer（懒加载单例）──
_tokenizer = None


def _get_tokenizer():
    """懒加载 DeepSeek V3 tokenizer（tokenizers 库 + 官方 tokenizer.json）。"""
    global _tokenizer
    if _tokenizer is None:
        from pathlib import Path
        from tokenizers import Tokenizer

        tok_path = Path(__file__).resolve().parent.parent / "deepseek_v3_tokenizer" / "deepseek_v3_tokenizer" / "tokenizer.json"
        _tokenizer = Tokenizer.from_file(str(tok_path))
    return _tokenizer


def estimate_tokens(messages: list[dict]) -> int:
    """使用 DeepSeek V3 官方 tokenizer 精确计算 token 数。"""
    import json

    tok = _get_tokenizer()
    total = 0
    for msg in messages:
        # content
        text = msg.get("content", "")
        if isinstance(text, str) and text:
            total += len(tok.encode(text).ids)
        # tool_calls → function.arguments
        tool_calls = msg.get("tool_calls")
        if tool_calls and isinstance(tool_calls, list):
            for tc in tool_calls:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                args = fn.get("arguments", "")
                if isinstance(args, str) and args:
                    total += len(tok.encode(args).ids)
        # reasoning_content
        reasoning = msg.get("reasoning_content", "")
        if isinstance(reasoning, str) and reasoning:
            total += len(tok.encode(reasoning).ids)
    return total
