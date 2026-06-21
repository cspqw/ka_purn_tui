# ── 项目级状态持久化 ─────────────────────────────────
"""ProjectState：小说项目级共享状态的持久化。

项目级数据（chapter_count/chapters）在同一项目的所有会话间共享，
存储于项目根目录的 .Project/project_state.json。

与 Session 的会话级数据（novel_memory/novel_progress）隔离：
- 切换会话：只切换会话级数据，项目级数据不变
- 切换项目：加载新项目的 project_state.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .novel_state import NovelState


class ProjectStateStore:
    """项目级状态读写工具。"""

    @staticmethod
    def _state_path(project_root: Path) -> Path:
        """项目状态文件路径：{project_root}/.Project/project_state.json。"""
        return project_root / ".Project" / "project_state.json"

    @staticmethod
    def _legacy_state_path(project_root: Path) -> Path:
        """旧版路径（.novel/），仅用于一次性迁移。"""
        return project_root / ".novel" / "project_state.json"

    @staticmethod
    def load(project_root: Path | None) -> dict[str, Any]:
        """从项目目录加载项目级状态。返回空 dict 表示无状态或加载失败。

        若新路径不存在但旧路径（.novel/）存在，自动迁移到 .Project/。
        """
        if project_root is None:
            return {}
        path = ProjectStateStore._state_path(project_root)
        if not path.exists():
            # 轻量迁移：旧路径存在则读取并保存到新路径
            legacy = ProjectStateStore._legacy_state_path(project_root)
            if legacy.exists():
                try:
                    with open(legacy, encoding="utf-8") as f:
                        data = json.load(f)
                    ProjectStateStore.save(project_root, data)
                    return data
                except Exception:  # noqa: BLE001
                    return {}
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def save(project_root: Path | None, data: dict[str, Any]) -> None:
        """保存项目级状态到项目目录。"""
        if project_root is None:
            return
        path = ProjectStateStore._state_path(project_root)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def load_to_state(state: NovelState) -> None:
        """从项目目录加载项目级状态到 NovelState。"""
        data = ProjectStateStore.load(state.project_root)
        if data:
            state.restore_project_state(data)

    @staticmethod
    def save_from_state(state: NovelState) -> None:
        """从 NovelState 保存项目级状态到项目目录。"""
        ProjectStateStore.save(state.project_root, state.save_project_state())
