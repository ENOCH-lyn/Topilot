from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from copilot_in_telegram.agent import AssistantPlanner
from copilot_in_telegram.config import Settings
from copilot_in_telegram.conversation_store import ConversationStore
from copilot_in_telegram.session_store import SessionStore

SendMessage = Callable[[int, str], Awaitable[None]]


class LiveProgress(Protocol):
    async def log(self, text: str) -> None: ...

    async def reply(self, text: str) -> None: ...

    async def close(self, final_text: str | None = None, failed: bool = False) -> None: ...


OpenLiveProgress = Callable[[int, str], Awaitable[LiveProgress]]


class TaskRunner:
    def __init__(self, settings: Settings, send_message: SendMessage, open_live_progress: OpenLiveProgress | None = None) -> None:
        self._settings = settings
        self._send_message = send_message
        self._open_live_progress = open_live_progress
        self._conversation = ConversationStore(settings.chat_db_path)
        self._sessions = SessionStore(settings.session_db_path)
        self._planner = AssistantPlanner(settings)

    async def start(self) -> None:
        return

    async def submit(self, chat_id: int, instruction: str) -> None:
        history = self._conversation.recent(chat_id)
        active_session_id = self._sessions.ensure_active_session(chat_id)
        self._sessions.touch(chat_id, active_session_id)

        live_progress = await self._start_live_progress(chat_id, instruction)
        try:
            plan = await self._planner.plan(
                active_session_id,
                history,
                instruction,
                progress_logger=live_progress.log if live_progress else None,
                reply_streamer=live_progress.reply if live_progress else None,
            )
        except Exception:
            if live_progress:
                await live_progress.close(failed=True)
            raise

        self._conversation.append_turn(chat_id, "user", instruction)

        if plan.reasoning_message and self._settings.copilot_cli_forward_reasoning and live_progress is None:
            await self._send_message(chat_id, f"[思考过程]\n{plan.reasoning_message}")

        reply = plan.assistant_message or self._planner.fallback_response()
        self._conversation.append_turn(chat_id, "assistant", reply)

        if live_progress:
            await live_progress.close(final_text=reply)
        else:
            await self._send_message(chat_id, reply)

    async def _start_live_progress(self, chat_id: int, instruction: str) -> LiveProgress | None:
        if self._open_live_progress is None:
            return None
        title = instruction.strip() or "Copilot 请求"
        if len(title) > 80:
            title = title[:80] + "..."
        return await self._open_live_progress(chat_id, title)

    def history_text(self, chat_id: int) -> str:
        turns = self._conversation.recent(chat_id, limit=12)
        if not turns:
            return "暂无对话记录。"
        lines = []
        for turn in turns:
            role = "你" if turn.role == "user" else "Copilot"
            content = turn.content.strip().replace("\n", " ")
            if len(content) > 80:
                content = content[:80] + "..."
            lines.append(f"{role}: {content}")
        return "最近对话:\n" + "\n".join(lines)

    def status_text(self, chat_id: int) -> str:
        session_id = self._sessions.ensure_active_session(chat_id)
        return f"后端状态: {self._planner.llm_status_text()}\n当前会话: {session_id}"

    def reset_text(self, chat_id: int) -> str:
        self._conversation.reset_chat(chat_id)
        return "当前 chat 的会话记忆已清空。"

    def llm_status_text(self) -> str:
        return self._planner.llm_status_text()

    def session_current_text(self, chat_id: int) -> str:
        session_id = self._sessions.ensure_active_session(chat_id)
        return f"当前 Copilot 会话: {session_id}"

    def session_list_text(self, chat_id: int) -> str:
        sessions = self._sessions.list_sessions(chat_id, limit=12)
        if not sessions:
            return "暂无会话。可用 /session_new 新建。"
        active = self._sessions.active_session(chat_id)
        lines = []
        for item in sessions:
            sid = str(item.get("id", ""))
            title = str(item.get("title", "session"))
            mark = "*" if sid == active else " "
            lines.append(f"{mark} {sid[:8]} | {title} | {item.get('last_used_at', '')}")
        return "Copilot 会话列表(*为当前):\n" + "\n".join(lines)

    def session_new_text(self, chat_id: int, title: str | None = None) -> str:
        session_id = self._sessions.create_session(chat_id, title=title or "manual-new")
        return f"已新建并切换会话: {session_id}"

    def session_use_text(self, chat_id: int, session_id_prefix: str) -> str:
        session_id = self._sessions.set_active(chat_id, session_id_prefix)
        if session_id is None:
            return f"未找到会话: {session_id_prefix}"
        return f"已切换到会话: {session_id}"
