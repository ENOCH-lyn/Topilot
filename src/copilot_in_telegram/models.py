from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class ActionType(StrEnum):
    RESPOND_ONLY = "respond_only"


@dataclass(slots=True)
class PlannedAction:
    action_type: ActionType
    summary: str
    assistant_message: str = ""
    reasoning_message: str = ""


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
