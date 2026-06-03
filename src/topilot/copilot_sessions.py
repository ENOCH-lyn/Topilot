from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class CopilotSessionInfo:
    session_id: str
    cwd: str | None
    model: str | None
    summary: str | None
    running: bool
    last_event_at: str | None
    history_lines: list[str]


class CopilotSessionInspector:
    """扫描本机 Copilot CLI 的 session-state 目录"""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or (Path.home() / ".copilot" / "session-state")

    def list_sessions(self, limit: int = 20) -> list[CopilotSessionInfo]:
        if not self._root.exists():
            return []

        infos: list[CopilotSessionInfo] = []
        for entry in self._root.iterdir():
            if not entry.is_dir():
                continue
            info = self.get_session(entry.name)
            if info:
                infos.append(info)

        def sort_key(item: CopilotSessionInfo) -> tuple[datetime, str]:
            stamp = _parse_iso(item.last_event_at)
            return (stamp or datetime.min.replace(tzinfo=timezone.utc), item.session_id)

        infos.sort(key=sort_key, reverse=True)
        return infos[:limit]

    def get_session(self, session_id: str) -> CopilotSessionInfo | None:
        folder = self._session_folder(session_id)
        if folder is None:
            return None
        if not folder.exists() or not folder.is_dir():
            return None

        workspace = _parse_workspace_yaml(folder / "workspace.yaml")
        cwd = workspace.get("cwd")
        summary = workspace.get("summary")
        running = any(path.name.startswith("inuse.") and path.suffix == ".lock" for path in folder.glob("inuse.*.lock"))

        events_path = folder / "events.jsonl"
        model: str | None = None
        last_event_at: str | None = None
        history_lines: list[str] = []
        if events_path.exists():
            tail_events = _read_tail_jsonl(events_path, max_lines=500)
            model = _extract_model(tail_events)
            last_event_at = _extract_last_timestamp(tail_events)
            history_lines = _extract_history_lines(tail_events, limit=12)

        return CopilotSessionInfo(
            session_id=session_id,
            cwd=cwd,
            model=model,
            summary=summary,
            running=running,
            last_event_at=last_event_at,
            history_lines=history_lines,
        )

    def delete_session(self, session_id: str) -> bool:
        folder = self._session_folder(session_id)
        if folder is None:
            return False
        if not folder.exists() or not folder.is_dir():
            return False
        for child in sorted(folder.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                child.rmdir()
        folder.rmdir()
        return True

    def _session_folder(self, session_id: str) -> Path | None:
        """把 session_id 限定为 session-state 根目录下的直接子目录名"""

        name = session_id.strip()
        if not name:
            return None
        candidate_name = Path(name)
        if candidate_name.is_absolute() or candidate_name.name != name:
            return None
        root = self._root.expanduser().resolve()
        folder = (root / name).resolve()
        if folder == root or root not in folder.parents:
            return None
        return folder


def _parse_workspace_yaml(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _read_tail_jsonl(path: Path, max_lines: int = 500, max_bytes: int = 300_000) -> list[dict]:
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raw = raw[-max_bytes:]
    text = raw.decode("utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines = lines[-max_lines:]
    items: list[dict] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            items.append(payload)
    return items


def _extract_model(events: list[dict]) -> str | None:
    for event in reversed(events):
        event_type = str(event.get("type", ""))
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        if event_type == "session.model_change":
            value = data.get("newModel")
            if isinstance(value, str) and value:
                return value
        if event_type == "session.resume":
            value = data.get("selectedModel")
            if isinstance(value, str) and value:
                return value
        if event_type == "session.shutdown":
            value = data.get("currentModel")
            if isinstance(value, str) and value:
                return value
        value = data.get("model")
        if isinstance(value, str) and value:
            return value
    return None


def _extract_last_timestamp(events: list[dict]) -> str | None:
    for event in reversed(events):
        ts = event.get("timestamp")
        if isinstance(ts, str) and ts:
            return ts
    return None


def _extract_history_lines(events: list[dict], limit: int = 12) -> list[str]:
    lines: list[str] = []
    for event in events:
        event_type = str(event.get("type", ""))
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        if event_type == "user.message":
            content = data.get("content")
            if isinstance(content, str) and content.strip():
                lines.append(f"[用户] {_compact(content)}")
        elif event_type == "assistant.message":
            content = data.get("content")
            if isinstance(content, str) and content.strip():
                lines.append(f"[助手] {_compact(content)}")
    return lines[-limit:]


def _compact(text: str, limit: int = 180) -> str:
    single = " ".join(text.split())
    if len(single) <= limit:
        return single
    return single[:limit] + "..."


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None
