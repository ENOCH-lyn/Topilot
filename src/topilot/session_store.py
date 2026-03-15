from __future__ import annotations
"""Copilot 会话持久化模块"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    """返回当前 UTC 时间（ISO8601）"""

    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """管理每个 Telegram chat 对应的 Copilot 会话列表与当前会话"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._payload: dict[str, dict] = {"active": {}, "sessions": {}}
        self._load()

    def _load(self) -> None:
        if not self._db_path.exists():
            self._payload = {"active": {}, "sessions": {}}
            return
        raw = self._db_path.read_text(encoding="utf-8").strip()
        if not raw:
            self._payload = {"active": {}, "sessions": {}}
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"active": {}, "sessions": {}}
        if not isinstance(payload, dict):
            payload = {"active": {}, "sessions": {}}
        payload.setdefault("active", {})
        payload.setdefault("sessions", {})
        payload.setdefault("models", {})
        self._payload = payload

    def save(self) -> None:
        """写回 JSON 文件"""

        self._db_path.write_text(json.dumps(self._payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _chat_key(self, chat_id: int) -> str:
        return str(chat_id)

    def _chat_sessions(self, chat_id: int) -> list[dict]:
        key = self._chat_key(chat_id)
        sessions = self._payload["sessions"].setdefault(key, [])
        if not isinstance(sessions, list):
            sessions = []
            self._payload["sessions"][key] = sessions
        return sessions

    def _find_session(self, chat_id: int, session_id: str) -> dict[str, Any] | None:
        for item in self._chat_sessions(chat_id):
            if str(item.get("id", "")) == session_id:
                return item
        return None

    def ensure_active_session(self, chat_id: int) -> str:
        """确保 chat 存在可用会话，不存在则自动创建"""

        active = self.active_session(chat_id)
        if active:
            self.touch(chat_id, active)
            return active
        session_id = self.create_session(chat_id, title="default")
        return session_id

    def active_session(self, chat_id: int) -> str | None:
        key = self._chat_key(chat_id)
        value = self._payload["active"].get(key)
        if isinstance(value, str) and value:
            return value
        return None

    def create_session(self, chat_id: int, title: str | None = None) -> str:
        """创建新会话并设置为当前激活会话"""

        session_id = str(uuid4())
        entry = {
            "id": session_id,
            "title": title or "new-session",
            "created_at": _now_iso(),
            "last_used_at": _now_iso(),
        }
        sessions = self._chat_sessions(chat_id)
        sessions.insert(0, entry)
        self._payload["active"][self._chat_key(chat_id)] = session_id
        self.save()
        return session_id

    def upsert_session(
        self,
        chat_id: int,
        session_id: str,
        title: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        source: str = "discovered",
        last_event_at: str | None = None,
        running: bool | None = None,
    ) -> dict[str, Any]:
        """新增或更新会话元数据"""

        existing = self._find_session(chat_id, session_id)
        if existing is None:
            existing = {
                "id": session_id,
                "title": title or "adopted-session",
                "created_at": _now_iso(),
                "last_used_at": _now_iso(),
            }
            self._chat_sessions(chat_id).insert(0, existing)

        if title:
            existing["title"] = title
        if cwd:
            existing["cwd"] = cwd
        if model:
            existing["model"] = model
        existing["source"] = source
        if last_event_at:
            existing["last_event_at"] = last_event_at
        if running is not None:
            existing["running"] = running
        existing["last_used_at"] = _now_iso()
        self.save()
        return existing

    def list_sessions(self, chat_id: int, limit: int = 20) -> list[dict]:
        """按最近使用时间排序返回会话列表"""

        sessions = list(self._chat_sessions(chat_id))
        sessions.sort(key=lambda item: item.get("last_used_at", ""), reverse=True)
        return sessions[:limit]

    def set_active(self, chat_id: int, session_id_prefix: str) -> str | None:
        """根据会话 ID 前缀切换当前会话"""

        needle = session_id_prefix.strip().lower()
        if not needle:
            return None
        for item in self._chat_sessions(chat_id):
            session_id = str(item.get("id", ""))
            if session_id.lower().startswith(needle):
                self._payload["active"][self._chat_key(chat_id)] = session_id
                item["last_used_at"] = _now_iso()
                self.save()
                return session_id
        return None

    def delete_session(self, chat_id: int, session_id: str) -> bool:
        """删除会话记录"""

        sessions = self._chat_sessions(chat_id)
        before = len(sessions)
        sessions[:] = [item for item in sessions if str(item.get("id", "")) != session_id]
        changed = len(sessions) != before

        key = self._chat_key(chat_id)
        if self._payload.get("active", {}).get(key) == session_id:
            self._payload.setdefault("active", {}).pop(key, None)
            changed = True

        if changed:
            self.save()
        return changed

    def get_session(self, chat_id: int, session_id: str) -> dict[str, Any] | None:
        """按会话 ID 获取会话元数据"""

        item = self._find_session(chat_id, session_id)
        return dict(item) if item else None

    def touch(self, chat_id: int, session_id: str) -> None:
        """更新会话最近使用时间"""

        changed = False
        for item in self._chat_sessions(chat_id):
            if item.get("id") == session_id:
                item["last_used_at"] = _now_iso()
                changed = True
                break
        if changed:
            self.save()

    def active_model(self, chat_id: int) -> str | None:
        """返回当前 chat 选择的模型（若未设置则返回 None）"""
        key = self._chat_key(chat_id)
        value = self._payload.get("models", {}).get(key)
        if isinstance(value, str) and value:
            return value
        return None

    def set_model(self, chat_id: int, model: str) -> None:
        """为指定 chat 保存模型选择"""
        key = self._chat_key(chat_id)
        self._payload.setdefault("models", {})[key] = model
        self.save()
