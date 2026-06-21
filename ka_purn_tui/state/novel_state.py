# ── 小说模式集中状态层 ─────────────────────────────────
"""NovelState：章节/待办/文件树/当前编辑文件的集中 reactive 数据源。

工具执行时修改这些字段，Textual 自动触发依赖面板的 watch_*/recompose。
为避免与 Textual reactive 的 Message 循环冲突，这里用普通 dataclass +
显式事件通知（App 通过 watch_novel_state 感知变更并刷新面板）。

常驻记忆层（Layer 1）：characters / world_settings / outline / style_guide
章节摘要层（Layer 2）：chapter_summaries
这两层会序列化注入到 system prompt，永久保留，不被上下文裁剪。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChapterInfo:
    """单章信息。"""

    index: int          # 1-based
    title: str
    done: bool = False

    def to_dict(self) -> dict:
        return {"index": self.index, "title": self.title, "done": self.done}

    @classmethod
    def from_dict(cls, data: dict) -> ChapterInfo:
        return cls(
            index=int(data.get("index", 0)),
            title=data.get("title", ""),
            done=bool(data.get("done", False)),
        )


@dataclass
class TodoItem:
    """待办项。"""

    text: str
    done: bool = False
    status: str = "pending"  # pending | active | done

    def to_dict(self) -> dict:
        return {"text": self.text, "done": self.done, "status": self.status}

    @classmethod
    def from_dict(cls, data: dict) -> TodoItem:
        return cls(
            text=data.get("text", ""),
            done=bool(data.get("done", False)),
            status=data.get("status", "done" if data.get("done") else "pending"),
        )


@dataclass
class FileNode:
    """文件树节点。"""

    name: str
    path: str
    is_dir: bool = False
    children: list[FileNode] = field(default_factory=list)


@dataclass
class NovelState:
    """小说模式运行时状态（非 reactive，由 App 持有并通过事件刷新 UI）。"""

    chapter_count: int = 0
    current_chapter: int | None = None
    chapters: list[ChapterInfo] = field(default_factory=list)
    todos: list[TodoItem] = field(default_factory=list)
    project_root: Path | None = None
    project_name: str = ""
    current_file: str | None = None          # 模型正在操作的文件（相对项目根）
    current_file_content: str = ""           # 实时内容
    file_tree: list[FileNode] = field(default_factory=list)
    follow: bool = True                      # 文件预览是否自动跟随到底部

    # ── 文件预览双模式 ──
    preview_file: str | None = None          # 当前预览的文件路径（相对项目根）
    preview_content: str = ""                # 预览文件内容
    preview_source: str = "model"            # "model"（模型操作） | "user"（用户点击）

    # ── 常驻记忆层（Layer 1）：永久保留，注入 system prompt ──
    # 人物卡：{name: {role, traits, appearance, relations}}
    characters: dict[str, dict] = field(default_factory=dict)
    # 世界观设定：{category: content}
    world_settings: dict[str, str] = field(default_factory=dict)
    # 大纲：[{index, summary}]
    outline: list[dict] = field(default_factory=list)
    # 写作风格说明
    style_guide: str = ""

    # ── 章节摘要层（Layer 2）：已完成章节的摘要，注入 system prompt ──
    # {chapter_index: summary_text}
    chapter_summaries: dict[int, str] = field(default_factory=dict)

    # ── 自定义进度（由模型通过 set_progress 工具管理，项目级持久化）──
    progress_current: int = 0
    progress_total: int = 0
    progress_label: str = ""

    # ── 预删除列表（瞬态，不持久化）──
    # 每项: {"original": Path, "pre_delete": Path, "display": str}
    _pre_delete_items: list[dict] = field(default_factory=list)

    # ── 章节工具 ──
    def set_chapter_count(self, count: int) -> str:
        self.chapter_count = max(0, count)
        # 同步扩展/收缩 chapters 列表
        while len(self.chapters) < self.chapter_count:
            self.chapters.append(ChapterInfo(index=len(self.chapters) + 1, title=f"第{len(self.chapters) + 1}章"))
        if len(self.chapters) > self.chapter_count:
            self.chapters = self.chapters[: self.chapter_count]
        # 重设章节数意味着新一季/新书开始，重置所有已完成标记
        for c in self.chapters:
            c.done = False
        return f"已设定总章数: {self.chapter_count}"

    def set_current_chapter(self, index: int, title: str = "") -> str:
        if self.chapter_count == 0:
            return "请先调用 set_chapter_count 设定总章数"
        if not (1 <= index <= self.chapter_count):
            return f"章节序号越界: {index}（总 {self.chapter_count} 章）"
        self.current_chapter = index
        self.chapters[index - 1].done = False  # 开始写某章时自动撤销完成状态
        if title:
            self.chapters[index - 1].title = title
        return f"正在写第 {index} 章: {self.chapters[index - 1].title}"

    def mark_chapter_done(self, index: int) -> str:
        if not (1 <= index <= len(self.chapters)):
            return f"章节序号越界: {index}"
        self.chapters[index - 1].done = True
        return f"第 {index} 章已标记完成"

    # ── 自定义进度工具 ──
    def set_progress(self, current: int, total: int, label: str = "") -> str:
        self.progress_current = current
        self.progress_total = total
        if label:
            self.progress_label = label
        pct = (current / total * 100) if total > 0 else 0
        return f"进度: {current}/{total} ({pct:.0f}%){' - ' + self.progress_label if self.progress_label else ''}"

    # ── 待办工具 ──
    def update_todo(self, items: list[dict]) -> str:
        self.todos = [
            TodoItem(
                text=it.get("text", ""),
                done=it.get("done", False),
                status=it.get("status", "done" if it.get("done") else "pending"),
            )
            for it in items
        ]
        return f"待办已更新（{len(self.todos)} 项）"

    def add_todo_item(self, text: str) -> str:
        self.todos.append(TodoItem(text=text))
        return f"已追加待办: {text}"

    def complete_todo_item(self, index: int) -> str:
        if not (0 <= index < len(self.todos)):
            return f"待办序号越界: {index}"
        self.todos[index].done = True
        self.todos[index].status = "done"
        return f"待办已完成: {self.todos[index].text}"

    # ── 常驻记忆工具 ──
    def update_character_card(
        self,
        name: str,
        role: str = "",
        traits: str = "",
        appearance: str = "",
        relations: str = "",
    ) -> str:
        """新增或更新人物卡。空字段不覆盖已有值。"""
        if not name:
            return "name 不能为空"
        card = self.characters.get(name, {})
        if role:
            card["role"] = role
        if traits:
            card["traits"] = traits
        if appearance:
            card["appearance"] = appearance
        if relations:
            card["relations"] = relations
        self.characters[name] = card
        return f"已更新人物卡: {name}（{card.get('role', '未设定角色')}）"

    def update_world_setting(self, category: str, content: str) -> str:
        """新增或更新世界观设定。"""
        if not category:
            return "category 不能为空"
        self.world_settings[category] = content
        return f"已更新世界观设定: {category}（{len(content)} 字）"

    def update_outline(self, chapters: list[dict]) -> str:
        """整体更新大纲。chapters: [{index, summary}]。"""
        self.outline = [
            {"index": int(c.get("index", 0)), "summary": c.get("summary", "")}
            for c in chapters
        ]
        return f"大纲已更新（{len(self.outline)} 章）"

    def update_style_guide(self, text: str) -> str:
        """更新写作风格说明。"""
        self.style_guide = text
        return f"写作风格已更新（{len(text)} 字）"

    def set_chapter_summary(self, index: int, summary: str) -> str:
        """设置某章的摘要（由 mark_chapter_done 后台摘要流程调用）。"""
        self.chapter_summaries[index] = summary
        return f"第 {index} 章摘要已保存（{len(summary)} 字）"

    # ── 常驻记忆序列化（注入 system prompt）──
    def render_memory_block(self) -> str:
        """把常驻记忆 + 章节摘要渲染成一段 markdown，供注入 system prompt。

        如果没有任何记忆，返回空字符串（调用方需自行判断是否拼接）。
        """
        lines: list[str] = []
        if self.characters:
            lines.append("【人物卡】")
            for name, card in self.characters.items():
                role = card.get("role", "")
                traits = card.get("traits", "")
                appearance = card.get("appearance", "")
                relations = card.get("relations", "")
                parts = [f"- {name}"]
                if role:
                    parts.append(f"（{role}）")
                lines.append("".join(parts))
                if traits:
                    lines.append(f"  性格: {traits}")
                if appearance:
                    lines.append(f"  外貌: {appearance}")
                if relations:
                    lines.append(f"  关系: {relations}")
        if self.world_settings:
            lines.append("【世界观设定】")
            for cat, content in self.world_settings.items():
                lines.append(f"- {cat}: {content}")
        if self.outline:
            lines.append("【大纲】")
            for ch in self.outline:
                idx = ch.get("index", "?")
                summary = ch.get("summary", "")
                lines.append(f"- 第{idx}章: {summary}")
        if self.style_guide:
            lines.append("【写作风格】")
            lines.append(self.style_guide)
        if self.chapter_summaries:
            lines.append("【已完成章节摘要】")
            for idx in sorted(self.chapter_summaries.keys()):
                lines.append(f"- 第{idx}章: {self.chapter_summaries[idx]}")
        return "\n".join(lines)

    # ── 进度统计 ──
    @property
    def done_chapter_count(self) -> int:
        return sum(1 for c in self.chapters if c.done)

    @property
    def progress_pct(self) -> float:
        if self.chapter_count == 0:
            return 0.0
        return self.done_chapter_count / self.chapter_count * 100.0

    # ── 会话级状态快照（常驻记忆 + 创作进度）──
    def save_session_state(self) -> dict:
        """导出会话级状态（常驻记忆 + 创作进度），用于持久化到 Session。

        项目级数据（chapter_count/chapters）不在此处，由 ProjectState 管理。
        """
        return {
            "novel_memory": {
                "characters": {k: dict(v) for k, v in self.characters.items()},
                "world_settings": dict(self.world_settings),
                "outline": [dict(o) for o in self.outline],
                "style_guide": self.style_guide,
                "chapter_summaries": dict(self.chapter_summaries),
            },
            "novel_progress": {
                "current_chapter": self.current_chapter,
                "todos": [t.to_dict() for t in self.todos],
            },
        }

    def restore_session_state(self, data: dict) -> None:
        """从 Session 恢复会话级状态（常驻记忆 + 创作进度）。

        不会恢复项目级数据（chapter_count/chapters），那些由 ProjectState 管理。
        """
        mem = data.get("novel_memory", {})
        self.characters = {k: dict(v) for k, v in mem.get("characters", {}).items()}
        self.world_settings = dict(mem.get("world_settings", {}))
        self.outline = [dict(o) for o in mem.get("outline", [])]
        self.style_guide = mem.get("style_guide", "")
        self.chapter_summaries = {int(k): v for k, v in mem.get("chapter_summaries", {}).items()}
        prog = data.get("novel_progress", {})
        self.current_chapter = prog.get("current_chapter")
        self.todos = [TodoItem.from_dict(t) for t in prog.get("todos", [])]

    def reset_session_state(self) -> None:
        """重置会话级状态（新建会话时调用）。

        保留项目级数据（chapter_count/chapters/project_root/project_name）。
        """
        self.characters = {}
        self.world_settings = {}
        self.outline = []
        self.style_guide = ""
        self.chapter_summaries = {}
        self.current_chapter = None
        self.todos = []

    # ── 项目级状态快照（chapter_count/chapters）──
    def save_project_state(self) -> dict:
        """导出项目级状态，用于持久化到 .Project/project_state.json。"""
        return {
            "chapter_count": self.chapter_count,
            "chapters": [c.to_dict() for c in self.chapters],
            "progress_current": self.progress_current,
            "progress_total": self.progress_total,
            "progress_label": self.progress_label,
        }

    def restore_project_state(self, data: dict) -> None:
        """从 .Project/project_state.json 恢复项目级状态。"""
        self.chapter_count = int(data.get("chapter_count", 0))
        self.chapters = [ChapterInfo.from_dict(c) for c in data.get("chapters", [])]
        self.progress_current = int(data.get("progress_current", 0))
        self.progress_total = int(data.get("progress_total", 0))
        self.progress_label = str(data.get("progress_label", ""))
