# ── 会话选择模态屏 ─────────────────────────────────
"""SessionsScreen：模态屏展示历史会话列表，支持选择/新建/删除。

按键：
  ↑/↓ 或 j/k  上下移动
  Enter       载入选中会话
  n           新建会话（载入空白会话，由 App 处理）
  d           删除选中会话（二次确认）
  Esc         关闭
"""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, ListItem, ListView

from ..state.session_store import Session


def _format_time(iso: str) -> str:
    """ISO 时间转可读格式，失败则原样返回。"""
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return iso


def _session_label(session: Session, index: int, current_id: str | None) -> str:
    """构造列表项显示文本。"""
    mode_tag = "小说" if session.mode == "novel" else "聊天"
    msg_count = len(session.messages)
    time_str = _format_time(session.updated_at)
    cur = " ★" if session.id == current_id else ""
    name = session.name or "未命名"
    return f"#{index + 1:<2} [{mode_tag}] {name}  ({msg_count}条, {time_str}){cur}"


class SessionsScreen(ModalScreen[str | None]):
    """会话选择模态屏。

    返回值：
      - Session.id：载入该会话
      - "__new__"：新建会话
      - None：取消
    """

    CSS = """
    SessionsScreen {
        align: center middle;
    }
    SessionsScreen > Vertical {
        width: 80;
        max-width: 90%;
        height: 28;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    SessionsScreen > Vertical > Label.title {
        color: $accent;
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    SessionsScreen > Vertical > ListView {
        height: 1fr;
        border: round $primary;
    }
    SessionsScreen > Vertical > Label.hint {
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "关闭", show=True),
        Binding("n", "new", "新建", show=True),
        Binding("d", "delete", "删除", show=True),
    ]

    def __init__(self, sessions: list[Session], current_id: str | None) -> None:
        super().__init__()
        self._sessions = sessions
        self._current_id = current_id

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("历史会话（↑↓选择 · Enter载入 · n新建 · d删除 · Esc关闭）", classes="title")
            if not self._sessions:
                yield Label("（暂无历史会话，按 n 新建）", classes="hint")
            else:
                items = [
                    ListItem(Label(_session_label(s, i, self._current_id)))
                    for i, s in enumerate(self._sessions)
                ]
                yield ListView(*items, id="sessions-list")
            yield Label("提示：★ 标记当前会话", classes="hint")
        yield Footer()

    def on_mount(self) -> None:
        try:
            lv = self.query_one("#sessions-list", ListView)
            lv.focus()
            # 默认高亮当前会话
            if self._current_id:
                for i, s in enumerate(self._sessions):
                    if s.id == self._current_id:
                        lv.index = i
                        break
        except Exception:
            pass

    # ── 动作 ──
    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """ListView 选中项事件（Enter 键触发）。"""
        # 通过 item 的索引找到对应会话
        try:
            lv = self.query_one("#sessions-list", ListView)
            idx = lv.index
            if idx is None or idx >= len(self._sessions):
                self.dismiss(None)
                return
            self.dismiss(self._sessions[idx].id)
        except Exception:
            self.dismiss(None)

    def action_new(self) -> None:
        self.dismiss("__new__")

    def action_delete(self) -> None:
        try:
            lv = self.query_one("#sessions-list", ListView)
            idx = lv.index
            if idx is None or idx >= len(self._sessions):
                return
            session = self._sessions[idx]
            # 简单二次确认：再按一次 d 才删除
            if getattr(self, "_confirm_delete", None) == idx:
                self._sessions.pop(idx)
                lv.clear()
                for i, s in enumerate(self._sessions):
                    lv.append(ListItem(Label(_session_label(s, i, self._current_id))))
                # 通过特殊返回值通知 App 删除
                self.dismiss(f"__delete__:{session.id}")
            else:
                self._confirm_delete = idx
                # 更新提示
                try:
                    hint = self.query_one("Vertical > Label.hint", Label)
                    hint.update(f"再按一次 d 确认删除：{session.name}（按其他键取消）")
                except Exception:
                    pass
        except Exception:
            pass

    def on_key(self, event) -> None:  # noqa: ANN001
        # 任意非 d 键取消删除确认
        if event.key != "d" and getattr(self, "_confirm_delete", None) is not None:
            self._confirm_delete = None
            try:
                hint = self.query_one("Vertical > Label.hint", Label)
                hint.update("提示：★ 标记当前会话")
            except Exception:
                pass
