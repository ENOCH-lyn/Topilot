from __future__ import annotations

import json
from pathlib import Path

from topilot.copilot_sessions import CopilotSessionInspector


def _write_jsonl(path: Path, items: list[dict]) -> None:
    lines = [json.dumps(item, ensure_ascii=False) for item in items]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_inspector_reads_workspace_model_running_state_and_history(tmp_path: Path) -> None:
    root = tmp_path / "session-state"
    session_dir = root / "session-1"
    session_dir.mkdir(parents=True)
    (session_dir / "workspace.yaml").write_text(
        'cwd: "C:/repo"\nsummary: "Topilot 会话"\n',
        encoding="utf-8",
    )
    (session_dir / "inuse.123.lock").write_text("", encoding="utf-8")
    _write_jsonl(
        session_dir / "events.jsonl",
        [
            {"type": "user.message", "timestamp": "2026-05-03T10:00:00Z", "data": {"content": "你好"}},
            {"type": "assistant.message", "timestamp": "2026-05-03T10:00:01Z", "data": {"content": "你好，我在。"}},
            {"type": "session.model_change", "timestamp": "2026-05-03T10:00:02Z", "data": {"newModel": "gpt-5"}},
        ],
    )

    inspector = CopilotSessionInspector(root)
    info = inspector.get_session("session-1")

    assert info is not None
    assert info.cwd == "C:/repo"
    assert info.summary == "Topilot 会话"
    assert info.model == "gpt-5"
    assert info.running is True
    assert info.last_event_at == "2026-05-03T10:00:02Z"
    assert info.history_lines == ["[用户] 你好", "[助手] 你好，我在。"]


def test_inspector_lists_by_latest_event_and_can_delete_session(tmp_path: Path) -> None:
    root = tmp_path / "session-state"
    first = root / "session-a"
    second = root / "session-b"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    _write_jsonl(
        first / "events.jsonl",
        [{"type": "assistant.message", "timestamp": "2026-05-03T09:00:00Z", "data": {"content": "older"}}],
    )
    _write_jsonl(
        second / "events.jsonl",
        [{"type": "assistant.message", "timestamp": "2026-05-03T11:00:00Z", "data": {"content": "newer"}}],
    )

    inspector = CopilotSessionInspector(root)
    sessions = inspector.list_sessions()

    assert [item.session_id for item in sessions[:2]] == ["session-b", "session-a"]
    assert inspector.delete_session("session-a") is True
    assert not first.exists()


def test_inspector_rejects_path_like_session_ids(tmp_path: Path) -> None:
    root = tmp_path / "session-state"
    session_dir = root / "session-1"
    session_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()

    inspector = CopilotSessionInspector(root)

    assert inspector.get_session("../outside") is None
    assert inspector.get_session(outside.as_posix()) is None
    assert inspector.delete_session("../outside") is False
    assert inspector.delete_session(outside.as_posix()) is False
    assert outside.exists()
    assert session_dir.exists()
