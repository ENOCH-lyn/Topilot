from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
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
        self._payload = payload

    def save(self) -> None:
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

    def ensure_active_session(self, chat_id: int) -> str:
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

    def list_sessions(self, chat_id: int, limit: int = 20) -> list[dict]:
        sessions = list(self._chat_sessions(chat_id))
        sessions.sort(key=lambda item: item.get("last_used_at", ""), reverse=True)
        return sessions[:limit]

    def set_active(self, chat_id: int, session_id_prefix: str) -> str | None:
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

    def touch(self, chat_id: int, session_id: str) -> None:
        changed = False
        for item in self._chat_sessions(chat_id):
            if item.get("id") == session_id:
                item["last_used_at"] = _now_iso()
                changed = True
                break
        if changed:
            self.save()
