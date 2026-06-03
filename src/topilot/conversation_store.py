from __future__ import annotations
"""对话历史存储模块"""

import json
from pathlib import Path

from topilot.models import ChatTurn


class ConversationStore:
    """按 chat 维度管理对话历史"""

    def __init__(self, db_path: Path, max_turns_per_chat: int = 40) -> None:
        self._db_path = db_path
        self._max_turns_per_chat = max_turns_per_chat
        self._conversations: dict[str, list[ChatTurn]] = {}
        self._load()

    def _load(self) -> None:
        if not self._db_path.exists():
            self._conversations = {}
            return
        raw_text = self._db_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            self._conversations = {}
            return
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            self._conversations = {}
            return
        if not isinstance(payload, dict):
            self._conversations = {}
            return
        conversations: dict[str, list[ChatTurn]] = {}
        for chat_id, turns in payload.items():
            if not isinstance(turns, list):
                continue
            parsed_turns: list[ChatTurn] = []
            for item in turns:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").strip()
                content = item.get("content")
                created_at = item.get("created_at")
                if not role or not isinstance(content, str):
                    continue
                if isinstance(created_at, str) and created_at:
                    parsed_turns.append(ChatTurn(role=role, content=content, created_at=created_at))
                else:
                    parsed_turns.append(ChatTurn(role=role, content=content))
            if parsed_turns:
                conversations[str(chat_id)] = parsed_turns
        self._conversations = conversations

    def save(self) -> None:
        """将当前内存状态持久化到 JSON 文件"""

        payload = {
            chat_id: [turn.to_dict() for turn in turns]
            for chat_id, turns in self._conversations.items()
        }
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def append_turn(self, chat_id: int, role: str, content: str) -> None:
        """追加单条对话，并在超过上限时裁剪旧消息"""

        key = str(chat_id)
        turns = self._conversations.setdefault(key, [])
        turns.append(ChatTurn(role=role, content=content))
        if len(turns) > self._max_turns_per_chat:
            self._conversations[key] = turns[-self._max_turns_per_chat :]
        self.save()

    def recent(self, chat_id: int, limit: int = 12) -> list[ChatTurn]:
        """获取最近 N 条对话"""

        turns = self._conversations.get(str(chat_id), [])
        return turns[-limit:]

    def reset_chat(self, chat_id: int) -> None:
        """清空指定 chat 的历史记录"""

        self._conversations.pop(str(chat_id), None)
        self.save()
