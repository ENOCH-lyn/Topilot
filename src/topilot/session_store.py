from __future__ import annotations
"""Copilot 会话持久化模块"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4


def _now_iso() -> str:
    """返回当前 UTC 时间（ISO8601）"""

    return datetime.now(timezone.utc).isoformat()


def _empty_payload() -> dict[str, Any]:
    """返回 sessions.json 的空结构"""

    return {"active": {}, "sessions": {}, "models": {}}


class SessionStore:
    """管理每个 Telegram chat 对应的 Copilot 会话列表与当前会话"""

    _locks_guard: ClassVar[threading.Lock] = threading.Lock()
    _locks: ClassVar[dict[str, threading.RLock]] = {}

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._payload: dict[str, Any] = _empty_payload()
        self._lock = self._resolve_lock(db_path)
        self._load()

    @classmethod
    def _resolve_lock(cls, db_path: Path) -> threading.RLock:
        key = str(db_path.expanduser().resolve())
        with cls._locks_guard:
            lock = cls._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                cls._locks[key] = lock
            return lock

    def _load(self) -> None:
        if not self._db_path.exists():
            self._payload = _empty_payload()
            return
        raw = self._db_path.read_text(encoding="utf-8").strip()
        if not raw:
            self._payload = _empty_payload()
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = _empty_payload()
        if not isinstance(payload, dict):
            payload = _empty_payload()

        active_raw = payload.get("active")
        active = {
            str(chat_id): session_id
            for chat_id, session_id in active_raw.items()
            if isinstance(session_id, str) and session_id
        } if isinstance(active_raw, dict) else {}

        sessions_raw = payload.get("sessions")
        sessions: dict[str, list[dict[str, Any]]] = {}
        if isinstance(sessions_raw, dict):
            for chat_id, items in sessions_raw.items():
                if not isinstance(items, list):
                    continue
                cleaned_items: list[dict[str, Any]] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    session_id = str(item.get("id") or "").strip()
                    if not session_id:
                        continue
                    cleaned = dict(item)
                    cleaned["id"] = session_id
                    cleaned_items.append(cleaned)
                sessions[str(chat_id)] = cleaned_items

        models_raw = payload.get("models")
        models = {
            str(chat_id): model
            for chat_id, model in models_raw.items()
            if isinstance(model, str) and model
        } if isinstance(models_raw, dict) else {}

        self._payload = {"active": active, "sessions": sessions, "models": models}

    def save(self) -> None:
        """写回 JSON 文件"""

        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path.write_text(json.dumps(self._payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _chat_key(self, chat_id: str | int) -> str:
        return str(chat_id)

    def _chat_sessions(self, chat_id: str | int) -> list[dict]:
        key = self._chat_key(chat_id)
        sessions = self._payload["sessions"].setdefault(key, [])
        if not isinstance(sessions, list):
            sessions = []
            self._payload["sessions"][key] = sessions
        return sessions

    def _find_session(self, chat_id: str | int, session_id: str) -> dict[str, Any] | None:
        for item in self._chat_sessions(chat_id):
            if str(item.get("id", "")) == session_id:
                return item
        return None

    def ensure_active_session(self, chat_id: str | int) -> str:
        """确保 chat 存在可用会话，不存在则自动创建"""

        with self._lock:
            self._load()
            active = self.active_session(chat_id)
            if active:
                self.touch(chat_id, active)
                return active
            session_id = self.create_session(chat_id, title="default")
            return session_id

    def active_session(self, chat_id: str | int) -> str | None:
        self._load()
        key = self._chat_key(chat_id)
        value = self._payload["active"].get(key)
        if isinstance(value, str) and value and self._find_session(chat_id, value):
            return value
        return None

    def create_session(self, chat_id: str | int, title: str | None = None) -> str:
        """创建新会话并设置为当前激活会话"""

        with self._lock:
            self._load()
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
            self._save_unlocked()
            return session_id

    def upsert_session(
        self,
        chat_id: str | int,
        session_id: str,
        title: str | None = None,
        cwd: str | None = None,
        model: str | None = None,
        source: str = "discovered",
        last_event_at: str | None = None,
        running: bool | None = None,
    ) -> dict[str, Any]:
        """新增或更新会话元数据"""

        with self._lock:
            self._load()
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
            self._save_unlocked()
            return dict(existing)

    def list_sessions(self, chat_id: str | int, limit: int = 20) -> list[dict]:
        """按最近使用时间排序返回会话列表"""

        with self._lock:
            self._load()
            sessions = list(self._chat_sessions(chat_id))
            sessions.sort(key=lambda item: item.get("last_used_at", ""), reverse=True)
            return sessions[:limit]

    def find_session_ids_by_prefix(self, chat_id: str | int, session_id_prefix: str) -> list[str]:
        """返回匹配指定前缀的会话 ID 列表"""

        with self._lock:
            self._load()
            needle = session_id_prefix.strip().lower()
            if not needle:
                return []
            matches: list[str] = []
            for item in self._chat_sessions(chat_id):
                session_id = str(item.get("id", ""))
                if session_id.lower().startswith(needle):
                    matches.append(session_id)
            return matches

    def set_active_exact(self, chat_id: str | int, session_id: str) -> str | None:
        """按完整会话 ID 设置当前激活会话"""

        with self._lock:
            self._load()
            if not self._find_session(chat_id, session_id):
                return None
            for item in self._chat_sessions(chat_id):
                if str(item.get("id", "")) == session_id:
                    self._payload["active"][self._chat_key(chat_id)] = session_id
                    item["last_used_at"] = _now_iso()
                    self._save_unlocked()
                    return session_id
            return None

    def set_active(self, chat_id: str | int, session_id_prefix: str) -> str | None:
        """根据会话 ID 前缀切换当前会话"""

        matches = self.find_session_ids_by_prefix(chat_id, session_id_prefix)
        if len(matches) != 1:
            return None
        return self.set_active_exact(chat_id, matches[0])

    def delete_session(self, chat_id: str | int, session_id: str) -> bool:
        """删除会话记录"""

        with self._lock:
            self._load()
            sessions = self._chat_sessions(chat_id)
            before = len(sessions)
            sessions[:] = [item for item in sessions if str(item.get("id", "")) != session_id]
            changed = len(sessions) != before

            key = self._chat_key(chat_id)
            if self._payload.get("active", {}).get(key) == session_id:
                self._payload.setdefault("active", {}).pop(key, None)
                changed = True

            if changed:
                self._save_unlocked()
            return changed

    def get_session(self, chat_id: str | int, session_id: str) -> dict[str, Any] | None:
        """按会话 ID 获取会话元数据"""

        with self._lock:
            self._load()
            item = self._find_session(chat_id, session_id)
            return dict(item) if item else None

    def touch(self, chat_id: str | int, session_id: str) -> None:
        """更新会话最近使用时间"""

        with self._lock:
            self._load()
            changed = False
            for item in self._chat_sessions(chat_id):
                if item.get("id") == session_id:
                    item["last_used_at"] = _now_iso()
                    changed = True
                    break
            if changed:
                self._save_unlocked()

    def active_model(self, chat_id: str | int) -> str | None:
        """返回当前 chat 选择的模型（若未设置则返回 None）"""
        with self._lock:
            self._load()
            key = self._chat_key(chat_id)
            value = self._payload.get("models", {}).get(key)
            if isinstance(value, str) and value:
                return value
            return None

    def set_model(self, chat_id: str | int, model: str) -> None:
        """为指定 chat 保存模型选择"""
        with self._lock:
            self._load()
            key = self._chat_key(chat_id)
            self._payload.setdefault("models", {})[key] = model
            self._save_unlocked()
