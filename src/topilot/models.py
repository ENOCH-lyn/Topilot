from __future__ import annotations
"""数据模型定义"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActionType(StrEnum):
    """规划动作类型"""

    RESPOND_ONLY = "respond_only"
    WAIT_USER_INPUT = "wait_user_input"


@dataclass(slots=True)
class PendingUserInput:
    """等待 Telegram 用户补充或确认的信息"""

    kind: str
    question: str
    session_id: str = ""
    options: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PendingUserInput":
        options_raw = payload.get("options")
        options = []
        if isinstance(options_raw, list):
            for item in options_raw:
                if not isinstance(item, str):
                    continue
                trimmed = item.strip()
                if trimmed:
                    options.append(trimmed)
        return cls(
            kind=str(payload.get("kind") or "ask_user").strip() or "ask_user",
            question=str(payload.get("question") or "").strip(),
            session_id=str(payload.get("session_id") or "").strip(),
            options=options,
            created_at=str(payload.get("created_at") or "").strip() or _now_iso(),
        )


@dataclass(slots=True)
class PlannedAction:
    """Planner 输出的单次动作计划"""

    action_type: ActionType
    summary: str
    assistant_message: str = ""
    reasoning_message: str = ""
    pending_user_input: PendingUserInput | None = None


@dataclass(slots=True)
class ChatTurn:
    """单条对话消息"""

    role: str
    content: str
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatTurn":
        return cls(**payload)
