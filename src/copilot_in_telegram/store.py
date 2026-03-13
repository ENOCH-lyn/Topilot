from __future__ import annotations

import json
from pathlib import Path

from copilot_in_telegram.models import TaskRecord


class TaskStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._tasks: dict[str, TaskRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self._db_path.exists():
            self._tasks = {}
            return
        raw_text = self._db_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            self._tasks = {}
            return
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            self._tasks = {}
            return
        if not isinstance(payload, list):
            self._tasks = {}
            return
        self._tasks = {item["id"]: TaskRecord.from_dict(item) for item in payload}

    def save(self) -> None:
        payload = [task.to_dict() for task in self._tasks.values()]
        self._db_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def upsert(self, task: TaskRecord) -> None:
        self._tasks[task.id] = task
        self.save()

    def get(self, task_id: str) -> TaskRecord | None:
        return self._tasks.get(task_id)

    def list_for_chat(self, chat_id: int, limit: int = 10) -> list[TaskRecord]:
        items = [task for task in self._tasks.values() if task.chat_id == chat_id]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]
