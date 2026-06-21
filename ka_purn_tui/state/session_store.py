# ── 会话存储与多会话管理 ─────────────────────────────────
"""SessionStore：管理多个对话会话的持久化与切换。

每个会话独立保存完整上下文（messages），支持新建、列出、载入、重命名、删除。
存储于项目根目录的 sessions.json，与 config.json 解耦避免配置文件膨胀。

会话分类：
- chat 模式会话：mode="chat"，novel_project=None
- novel 模式会话：mode="novel"，novel_project=项目名
  - 每个会话独立保存常驻记忆（novel_memory）和创作进度（novel_progress）
  - 项目级共享数据（chapter_count/chapters）由 ProjectState 管理
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    """当前时间的 ISO 格式字符串（本地时区）。"""
    return datetime.now().isoformat(timespec="seconds")


def _default_novel_memory() -> dict[str, Any]:
    """会话级常驻记忆默认结构。"""
    return {
        "characters": {},
        "world_settings": {},
        "outline": [],
        "style_guide": "",
        "chapter_summaries": {},
    }


def _default_novel_progress() -> dict[str, Any]:
    """会话级创作进度默认结构。"""
    return {
        "current_chapter": None,
        "todos": [],
    }


@dataclass
class Session:
    """单个对话会话。"""

    id: str
    name: str
    mode: str  # "chat" | "novel"
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    # novel 模式下关联的项目名（便于恢复时提示）
    novel_project: str | None = None
    # 会话级常驻记忆（仅 novel 模式有效，per-session 隔离）
    novel_memory: dict[str, Any] = field(default_factory=_default_novel_memory)
    # 会话级创作进度（仅 novel 模式有效，per-session 隔离）
    novel_progress: dict[str, Any] = field(default_factory=_default_novel_progress)

    def touch(self) -> None:
        self.updated_at = _now_iso()

    @classmethod
    def create(cls, name: str, mode: str, novel_project: str | None = None) -> Session:
        now = _now_iso()
        return cls(
            id=uuid.uuid4().hex[:8],
            name=name or "新会话",
            mode=mode,
            messages=[],
            created_at=now,
            updated_at=now,
            novel_project=novel_project,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            name=data.get("name", "未命名"),
            mode=data.get("mode", "chat"),
            messages=data.get("messages", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            novel_project=data.get("novel_project"),
            # 兼容旧会话：没有 novel_memory/novel_progress 字段时用默认值
            novel_memory={**_default_novel_memory(), **data.get("novel_memory", {})},
            novel_progress={**_default_novel_progress(), **data.get("novel_progress", {})},
        )


class SessionStore:
    """多会话持久化管理。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.sessions: dict[str, Session] = {}
        self.load()

    def load(self) -> None:
        """从磁盘加载所有会话。"""
        self.sessions.clear()
        if not self.path.exists():
            return
        try:
            import json

            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            for sid, sdata in data.get("sessions", {}).items():
                session = Session.from_dict(sdata)
                self.sessions[session.id] = session
        except Exception:
            # 损坏的文件不阻塞启动
            self.sessions.clear()

    def save(self) -> None:
        """持久化所有会话到磁盘。"""
        try:
            import json

            data = {
                "sessions": {sid: s.to_dict() for sid, s in self.sessions.items()},
                "version": 2,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ── 会话操作 ──
    def create(self, name: str, mode: str, novel_project: str | None = None) -> Session:
        """新建会话并持久化。"""
        session = Session.create(name, mode, novel_project)
        self.sessions[session.id] = session
        self.save()
        return session

    def list_sessions(
        self,
        mode: str | None = None,
        project: str | None = None,
    ) -> list[Session]:
        """按更新时间降序返回会话，支持按模式/项目过滤。

        - mode="chat"：只返回 chat 会话
        - mode="novel" + project="xxx"：只返回该项目的 novel 会话
        - 都不传：返回所有会话
        """
        result = list(self.sessions.values())
        if mode:
            result = [s for s in result if s.mode == mode]
        if project:
            result = [s for s in result if s.novel_project == project]
        return sorted(result, key=lambda s: s.updated_at, reverse=True)

    def get(self, sid: str) -> Session | None:
        return self.sessions.get(sid)

    def delete(self, sid: str) -> bool:
        if sid in self.sessions:
            del self.sessions[sid]
            self.save()
            return True
        return False

    def rename(self, sid: str, name: str) -> bool:
        session = self.sessions.get(sid)
        if session is None:
            return False
        session.name = name
        session.touch()
        self.save()
        return True

    def update_messages(self, sid: str, messages: list[dict[str, Any]]) -> None:
        """更新某会话的消息列表并刷新时间戳。"""
        session = self.sessions.get(sid)
        if session is None:
            return
        session.messages = [dict(m) for m in messages]
        session.touch()
        self.save()

    def count(self) -> int:
        return len(self.sessions)
