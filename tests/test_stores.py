from __future__ import annotations

from pathlib import Path

from topilot.conversation_store import ConversationStore
from topilot.task_runner import TaskRunner
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


def test_task_runner_status_text_includes_model_source_workspace_and_state(make_settings) -> None:
    settings = make_settings()

    async def _send_message(chat_id: int, text: str) -> None:
        return None

    runner = TaskRunner(settings, _send_message)
    session_id = runner._sessions.create_session(100, title="daily-work")
    runner._sessions.upsert_session(
        100,
        session_id,
        title="daily-work",
        cwd="C:/workspace/project-a",
        model="gpt-5",
        source="local",
        last_event_at="2026-05-05T10:20:30Z",
        running=True,
    )
    runner._sessions.set_model(100, "gpt-5")

    text = runner.status_text(100)

    assert "后端状态: Copilot CLI 已启用（model=gpt-5）" in text
    assert f"当前会话: {session_id}" in text
    assert "会话标题: daily-work" in text
    assert "会话来源: local" in text
    assert "会话状态: 运行中" in text
    assert "当前模型: gpt-5" in text
    assert "工作区: C:/workspace/project-a" in text
    assert "最近活动: 2026-05-05T10:20:30Z" in text
