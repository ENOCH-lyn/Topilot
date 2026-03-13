from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


class TaskState(StrEnum):
    RECEIVED = "received"
    PENDING_APPROVAL = "pending_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class EventType(StrEnum):
    ACCEPTED = "accepted"
    APPROVAL_REQUIRED = "approval_required"
    STARTED = "started"
    MILESTONE = "milestone"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class ActionType(StrEnum):
    RESPOND_ONLY = "respond_only"
    RUN_SHELL = "run_shell"
    BROWSE_URL = "browse_url"


@dataclass(slots=True)
class PlannedAction:
    action_type: ActionType
    summary: str
    assistant_message: str = ""
    reasoning_message: str = ""
    command: str | None = None
    url: str | None = None
    requires_approval: bool = False


@dataclass(slots=True)
class TaskRecord:
    chat_id: int
    instruction: str
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    state: TaskState = TaskState.RECEIVED
    summary: str = ""
    result_summary: str = ""
    command: str | None = None
    url: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    log_excerpt: str = ""

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskRecord":
        payload = dict(payload)
        payload["state"] = TaskState(payload["state"])
        return cls(**payload)


@dataclass(slots=True)
class NotificationEvent:
    event_type: EventType
    task: TaskRecord
    detail: str = ""


@dataclass(slots=True)
class ChatTurn:
    role: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatTurn":
        return cls(**payload)
