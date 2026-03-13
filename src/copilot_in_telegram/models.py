from __future__ import annotations
"""数据模型定义
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class ActionType(StrEnum):
    """规划动作类型"""

    RESPOND_ONLY = "respond_only"


@dataclass(slots=True)
class PlannedAction:
    """Planner 输出的单次动作计划"""

    action_type: ActionType
    summary: str
    assistant_message: str = ""
    reasoning_message: str = ""


@dataclass(slots=True)
class ChatTurn:
    """单条对话消息"""

    role: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatTurn":
        return cls(**payload)
