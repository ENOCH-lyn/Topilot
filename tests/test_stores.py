from __future__ import annotations

import asyncio
from pathlib import Path

from topilot.copilot_sessions import CopilotSessionInfo
from topilot.conversation_store import ConversationStore
from topilot.models import ActionType, PlannedAction
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


def test_conversation_store_skips_malformed_persisted_turns_and_creates_parent_dir(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "chats.json"
    db_path.parent.mkdir()
    db_path.write_text(
        """
        {
          "42": [
            {"role": "user", "content": "valid", "created_at": "2026-05-03T10:00:00Z"},
            {"role": "assistant"},
            "bad"
          ],
          "bad-chat": "not-a-list"
        }
        """,
        encoding="utf-8",
    )

    store = ConversationStore(db_path)
    assert [turn.content for turn in store.recent(42)] == ["valid"]

    missing_parent_path = tmp_path / "new-parent" / "chats.json"
    new_store = ConversationStore(missing_parent_path)
    new_store.append_turn(100, "user", "hello")

    assert missing_parent_path.exists()


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


def test_session_store_sanitizes_malformed_payload_and_stale_active_session(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "sessions.json"
    db_path.parent.mkdir()
    db_path.write_text(
        """
        {
          "active": {"100": "missing-session", "bad": 42},
          "sessions": {
            "100": [
              {"id": "valid-session", "title": "valid"},
              {"title": "missing-id"},
              "bad"
            ],
            "bad-chat": "not-a-list"
          },
          "models": {"100": "gpt-5", "bad": 42}
        }
        """,
        encoding="utf-8",
    )

    store = SessionStore(db_path)

    assert store.active_session(100) is None
    assert [item["id"] for item in store.list_sessions(100)] == ["valid-session"]
    assert store.active_model(100) == "gpt-5"

    missing_parent_path = tmp_path / "new-parent" / "sessions.json"
    new_store = SessionStore(missing_parent_path)
    new_store.create_session(100, title="created")

    assert missing_parent_path.exists()


def test_session_store_requires_unique_prefix_when_switching(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.json"
    store = SessionStore(db_path)

    first = "abc123-session-a"
    second = "abc456-session-b"
    store.upsert_session(100, first, title="first")
    store.upsert_session(100, second, title="second")

    assert set(store.find_session_ids_by_prefix(100, "abc")) == {first, second}
    assert store.set_active(100, "abc") is None
    assert store.active_session(100) is None
    assert store.set_active(100, "abc123") == first
    assert store.active_session(100) == first


def test_task_runner_status_text_includes_model_source_workspace_and_state(make_settings, tmp_path: Path) -> None:
    fake_copilot = tmp_path / "copilot.cmd"
    fake_copilot.write_text("@echo off\n", encoding="utf-8")
    settings = make_settings(copilot_cli_command=fake_copilot.as_posix())

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

    assert "后端状态: Copilot CLI 已就绪（model=gpt-5）" in text
    assert f"当前会话: {session_id}" in text
    assert "会话标题: daily-work" in text
    assert "会话来源: local" in text
    assert "会话状态: 运行中" in text
    assert "当前模型: gpt-5" in text
    assert "工作区: C:/workspace/project-a" in text
    assert "最近活动: 2026-05-05T10:20:30Z" in text


def test_task_runner_llm_diagnostic_text_exposes_backend_health(make_settings, tmp_path: Path) -> None:
    fake_copilot = tmp_path / "copilot.cmd"
    fake_copilot.write_text("@echo off\n", encoding="utf-8")
    settings = make_settings(copilot_cli_command=fake_copilot.as_posix())

    async def _send_message(chat_id: int, text: str) -> None:
        return None

    runner = TaskRunner(settings, _send_message)
    runner._cached_models = ["gpt-5-mini", "gpt-5"]
    runner._sessions.set_model(100, "gpt-5")

    text = runner.llm_diagnostic_text(100)

    assert "后端状态: Copilot CLI 已就绪（model=gpt-5）" in text
    assert f"配置命令: {fake_copilot.as_posix()}" in text
    assert f"解析命令: {fake_copilot.as_posix()}" in text
    assert "可用模型: gpt-5-mini, gpt-5" in text
    assert "待处理:" not in text


def test_task_runner_session_current_text_includes_brief_session_summary(make_settings) -> None:
    settings = make_settings()

    async def _send_message(chat_id: int, text: str) -> None:
        return None

    runner = TaskRunner(settings, _send_message)
    session_id = runner._sessions.create_session(100, title="quick-check")
    runner._sessions.upsert_session(
        100,
        session_id,
        title="quick-check",
        cwd="C:/workspace/mobile",
        model="gpt-5-mini",
        source="bot",
        running=False,
    )

    text = runner.session_current_text(100)

    assert f"当前 Copilot 会话: {session_id}" in text
    assert "会话标题: quick-check" in text
    assert "会话来源: bot" in text
    assert "会话状态: 空闲" in text
    assert "当前模型: gpt-5-mini" in text
    assert "工作区: C:/workspace/mobile" in text


def test_task_runner_prefers_live_local_session_metadata_for_summaries(make_settings) -> None:
    settings = make_settings()

    async def _send_message(chat_id: int, text: str) -> None:
        return None

    runner = TaskRunner(settings, _send_message)
    session_id = runner._sessions.create_session(100, title="old-title")
    runner._sessions.upsert_session(
        100,
        session_id,
        title="old-title",
        cwd="C:/old",
        model="gpt-5-mini",
        source="bot",
        running=False,
    )

    live_info = CopilotSessionInfo(
        session_id=session_id,
        cwd="C:/live",
        model="gpt-5",
        summary="live-title",
        running=True,
        last_event_at="2026-05-05T12:00:00Z",
        history_lines=[],
    )
    runner._inspector.get_session = lambda sid: live_info if sid == session_id else None
    runner._inspector.list_sessions = lambda limit=20: [live_info]

    current_text = runner.session_current_text(100)
    status_text = runner.status_text(100)
    menu_items = runner.session_menu_items(100)

    assert "会话标题: live-title" in current_text
    assert "会话来源: local" in current_text
    assert "会话状态: 运行中" in current_text
    assert "当前模型: gpt-5" in current_text
    assert "工作区: C:/live" in current_text
    assert "最近活动: 2026-05-05T12:00:00Z" in status_text
    assert menu_items[0]["title"] == "live-title"
    assert menu_items[0]["running"] is True
    assert menu_items[0]["source"] == "local"


def test_task_runner_submit_persists_default_session_metadata(make_settings) -> None:
    settings = make_settings(copilot_cli_model="gpt-5-mini")
    sent: list[tuple[int, str]] = []
    captured: dict[str, object] = {}

    async def _send_message(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    class FakePlanner:
        async def plan(self, session_id, history, instruction, **kwargs):
            captured["session_id"] = session_id
            captured["history"] = history
            captured["instruction"] = instruction
            captured["model"] = kwargs.get("model")
            captured["workspace_dir"] = kwargs.get("workspace_dir")
            return PlannedAction(
                action_type=ActionType.RESPOND_ONLY,
                summary="ok",
                assistant_message="done",
            )

    runner = TaskRunner(settings, _send_message)
    runner._planner = FakePlanner()

    import asyncio

    asyncio.run(runner.submit(100, "hello"))

    session_id = str(captured["session_id"])
    session_meta = runner._sessions.get_session(100, session_id) or {}

    assert captured["model"] == "gpt-5-mini"
    assert captured["workspace_dir"] is None
    assert session_meta["cwd"] == settings.workspace_root.as_posix()
    assert session_meta["model"] == "gpt-5-mini"
    assert session_meta["source"] == "bot"
    assert sent == [(100, "done")]


def test_task_runner_session_use_reports_ambiguous_stored_prefix(make_settings) -> None:
    settings = make_settings()

    async def _send_message(chat_id: int, text: str) -> None:
        return None

    runner = TaskRunner(settings, _send_message)
    runner._sessions.upsert_session(100, "abc123-session-a", title="first")
    runner._sessions.upsert_session(100, "abc456-session-b", title="second")

    text = runner.session_use_text(100, "abc")

    assert "会话前缀不唯一: abc" in text
    assert "abc123-sessi" in text
    assert "abc456-sessi" in text
    assert runner._sessions.active_session(100) is None


def test_task_runner_session_use_takes_over_unique_discovered_prefix(make_settings) -> None:
    settings = make_settings()

    async def _send_message(chat_id: int, text: str) -> None:
        return None

    runner = TaskRunner(settings, _send_message)
    live_info = CopilotSessionInfo(
        session_id="local-session-001",
        cwd="C:/live",
        model="gpt-5",
        summary="local work",
        running=False,
        last_event_at="2026-05-05T12:00:00Z",
        history_lines=[],
    )
    runner._inspector.get_session = lambda sid: live_info if sid == live_info.session_id else None
    runner._inspector.list_sessions = lambda limit=20: [live_info]

    text = runner.session_use_text(100, "local-session")

    assert text == "已接管会话: local-session-001"
    assert runner._sessions.active_session(100) == "local-session-001"
    assert runner._sessions.active_model(100) == "gpt-5"


def test_task_runner_start_and_model_helpers_refresh_cached_models(make_settings) -> None:
    settings = make_settings(copilot_available_models=["gpt-5-mini"])

    async def _send_message(chat_id: int, text: str) -> None:
        return None

    class FakePlanner:
        async def fetch_available_models(self) -> list[str]:
            return ["gpt-5", "gpt-5-mini", "claude-sonnet-4.6"]

        def llm_status_text(self, model: str | None = None) -> str:
            return "Copilot CLI 未就绪（命令未找到或不可执行: copilot）"

    runner = TaskRunner(settings, _send_message)
    runner._planner = FakePlanner()

    asyncio.run(runner.start())
    runner.set_model(100, "gpt-5")

    assert runner.list_models() == ["gpt-5", "gpt-5-mini", "claude-sonnet-4.6"]
    assert runner.current_model(100) == "gpt-5"
    assert runner.llm_status_text() == "Copilot CLI 未就绪（命令未找到或不可执行: copilot）"


def test_task_runner_session_menu_takeover_detail_history_and_live_payload(make_settings) -> None:
    settings = make_settings()

    async def _send_message(chat_id: int, text: str) -> None:
        return None

    runner = TaskRunner(settings, _send_message)
    stored_session = runner._sessions.create_session(100, title="stored")
    runner._sessions.upsert_session(
        100,
        stored_session,
        title="stored",
        cwd="C:/stored",
        model="gpt-5-mini",
        source="saved",
        last_event_at="2026-05-05T10:00:00Z",
        running=False,
    )

    local_running = CopilotSessionInfo(
        session_id="local-running",
        cwd="C:/live",
        model="gpt-5",
        summary="local session",
        running=True,
        last_event_at="2026-05-05T12:00:00Z",
        history_lines=["line-1", "line-2", "line-3"],
    )
    local_idle = CopilotSessionInfo(
        session_id="local-idle",
        cwd="C:/idle",
        model="gpt-4.1",
        summary="idle session",
        running=False,
        last_event_at="2026-05-05T11:00:00Z",
        history_lines=[],
    )
    session_map = {local_running.session_id: local_running, local_idle.session_id: local_idle}
    runner._inspector.list_sessions = lambda limit=20: [local_running, local_idle]
    runner._inspector.get_session = lambda sid: session_map.get(sid)
    runner._inspector.delete_session = lambda sid: sid == local_running.session_id

    refreshed = runner.refresh_discovered_sessions(limit=10)
    items = runner.session_menu_items(100, limit=10)
    takeover_text = runner.takeover_session(100, local_running.session_id)
    detail_text = runner.session_detail_text(100, local_running.session_id)
    history_text = runner.session_history_text(100, local_running.session_id)
    live_payload = runner.session_live_payload(100, local_running.session_id)

    assert refreshed[0]["id"] == "local-running"
    assert items[0]["id"] == "local-running"
    assert items[0]["running"] is True
    assert takeover_text == "已接管会话: local-running"
    assert "状态: 运行中" in detail_text
    assert "模型: gpt-5" in detail_text
    assert "最近历史:" in history_text
    assert "- line-3" in history_text
    assert live_payload["exists"] is True
    assert live_payload["running"] is True
    assert "会话: local-running" in str(live_payload["text"])


def test_task_runner_delete_and_missing_session_branches(make_settings) -> None:
    settings = make_settings()

    async def _send_message(chat_id: int, text: str) -> None:
        return None

    runner = TaskRunner(settings, _send_message)
    session_id = runner._sessions.create_session(100, title="stored")
    runner._sessions.upsert_session(100, session_id, title="stored", cwd="C:/workspace", model="gpt-5-mini")
    runner._inspector.delete_session = lambda sid: (_ for _ in ()).throw(RuntimeError("boom"))
    runner._inspector.get_session = lambda sid: None

    assert runner.delete_session(100, session_id) == "会话已删除"
    assert runner.delete_session(100, "missing") == "会话不存在或无法删除"
    assert runner.session_history_text(100, "missing") == "未找到该会话的历史"

    payload = runner.session_live_payload(100, "missing")
    assert payload["exists"] is False
    assert payload["signature"] == "missing:missing"


def test_task_runner_session_text_helpers_cover_empty_list_new_session_and_stored_fallback(make_settings) -> None:
    settings = make_settings()

    async def _send_message(chat_id: int, text: str) -> None:
        return None

    runner = TaskRunner(settings, _send_message)

    assert runner.session_list_text(100) == "暂无会话。可用 /session_new 新建"
    assert runner.session_use_text(100, "   ") == "未找到会话:    "

    created_text = runner.session_new_text(100, title="manual")
    session_id = runner._sessions.active_session(100)
    runner._sessions.upsert_session(
        100,
        session_id,
        title="manual",
        cwd="C:/manual",
        model="gpt-5-mini",
        source="saved",
        running=False,
    )
    runner._inspector.get_session = lambda sid: None

    assert created_text.startswith("已新建并切换会话: ")
    assert "manual" in runner.session_list_text(100)
    assert "当前激活: 是" in runner.session_detail_text(100, session_id)
    assert runner.takeover_session(100, "missing") == "未找到该会话"
