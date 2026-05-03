from __future__ import annotations

from pathlib import Path

from topilot.conversation_store import ConversationStore
from topilot.session_store import SessionStore


def test_conversation_store_trims_history_and_persists(tmp_path: Path) -> None:
    db_path = tmp_path / "chats.json"
    store = ConversationStore(db_path, max_turns_per_chat=3)

    store.append_turn(42, "user", "u1")
    store.append_turn(42, "assistant", "a1")
    store.append_turn(42, "user", "u2")
    store.append_turn(42, "assistant", "a2")

    reloaded = ConversationStore(db_path, max_turns_per_chat=3)
    turns = reloaded.recent(42, limit=10)

    assert [turn.content for turn in turns] == ["a1", "u2", "a2"]


def test_session_store_tracks_active_session_and_model(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.json"
    store = SessionStore(db_path)

    first = store.create_session(100, title="first")
    second = store.create_session(100, title="second")
    store.upsert_session(100, second, cwd="C:/workspace", model="gpt-5", source="local", running=True)
    store.set_model(100, "gpt-5")

    assert store.active_session(100) == second
    assert store.active_model(100) == "gpt-5"

    switched = store.set_active(100, first[:8])
    assert switched == first
    assert store.active_session(100) == first

    deleted = store.delete_session(100, first)
    assert deleted is True
    assert store.active_session(100) is None

    reloaded = SessionStore(db_path)
    remaining = reloaded.list_sessions(100)
    assert [item["id"] for item in remaining] == [second]
    assert reloaded.active_model(100) == "gpt-5"
