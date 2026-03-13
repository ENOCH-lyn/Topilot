from __future__ import annotations
"""对话编排模块"""

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from copilot_in_telegram.agent import AssistantPlanner
from copilot_in_telegram.config import Settings
from copilot_in_telegram.conversation_store import ConversationStore
from copilot_in_telegram.session_store import SessionStore

SendMessage = Callable[[int, str], Awaitable[None]]

logger = logging.getLogger(__name__)


class LiveProgress(Protocol):
    """流式输出接口协议"""

    async def log(self, text: str) -> None: ...

    async def reply(self, text: str) -> None: ...

    async def close(self, final_text: str | None = None, failed: bool = False) -> None: ...


OpenLiveProgress = Callable[[int, str], Awaitable[LiveProgress]]


class TaskRunner:
    """Telegram 消息到 Copilot CLI 的调度器"""

    def __init__(self, settings: Settings, send_message: SendMessage, open_live_progress: OpenLiveProgress | None = None) -> None:
        self._settings = settings
        self._send_message = send_message
        self._open_live_progress = open_live_progress
        self._conversation = ConversationStore(settings.chat_db_path)
        self._sessions = SessionStore(settings.session_db_path)
        self._planner = AssistantPlanner(settings)
        # 启动后会被实时结果覆盖
        self._cached_models: list[str] = list(settings.copilot_available_models)

    async def start(self) -> None:
        """启动时拉取实时模型列表并缓存"""
        self._cached_models = await self._planner.fetch_available_models()
        logger.info("可用模型: %s", self._cached_models)

    async def submit(self, chat_id: int, instruction: str) -> None:
        """处理一次用户请求并回传结果"""

        logger.info("收到请求 chat_id=%s instruction_len=%s", chat_id, len(instruction.strip()))

        history = self._conversation.recent(chat_id)
        active_session_id = self._sessions.ensure_active_session(chat_id)
        self._sessions.touch(chat_id, active_session_id)

        live_progress = await self._start_live_progress(chat_id, instruction)
        model = self._sessions.active_model(chat_id)
        try:
            plan = await self._planner.plan(
                active_session_id,
                history,
                instruction,
                model=model,
                progress_logger=live_progress.log if live_progress else None,
                reply_streamer=live_progress.reply if live_progress else None,
            )
        except Exception:
            logger.exception("请求处理失败 chat_id=%s session=%s", chat_id, active_session_id)
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

        logger.info("请求处理完成 chat_id=%s session=%s reply_len=%s", chat_id, active_session_id, len(reply))

    async def _start_live_progress(self, chat_id: int, instruction: str) -> LiveProgress | None:
        """按需创建流式展示对象"""

        if self._open_live_progress is None:
            return None
        title = instruction.strip() or "Copilot 请求"
        if len(title) > 80:
            title = title[:80] + "..."
        return await self._open_live_progress(chat_id, title)

    def status_text(self, chat_id: int) -> str:
        """返回后端状态与当前会话信息"""

        session_id = self._sessions.ensure_active_session(chat_id)
        model = self._sessions.active_model(chat_id)
        return f"后端状态: {self._planner.llm_status_text(model)}\n当前会话: {session_id}"

    def llm_status_text(self, chat_id: int | None = None) -> str:
        """返回 LLM 状态文本"""
        model = self._sessions.active_model(chat_id) if chat_id is not None else None
        return self._planner.llm_status_text(model)

    def current_model(self, chat_id: int) -> str:
        """返回当前 chat 有效的模型"""
        return self._sessions.active_model(chat_id) or self._settings.copilot_cli_model

    def list_models(self) -> list[str]:
        """返回可用模型列表

        数据来源是启动时拉取并缓存的结果
        """
        return list(self._cached_models)

    def set_model(self, chat_id: int, model: str) -> None:
        """为指定 chat 设置当前模型"""
        self._sessions.set_model(chat_id, model)
        logger.info("模型已切换 chat_id=%s model=%s", chat_id, model)

    def session_current_text(self, chat_id: int) -> str:
        """返回当前会话 ID"""
        session_id = self._sessions.ensure_active_session(chat_id)
        return f"当前 Copilot 会话: {session_id}"

    def session_list_text(self, chat_id: int) -> str:
        """返回会话列表文本，按最近使用时间排序，标记当前会话"""
        sessions = self._sessions.list_sessions(chat_id, limit=12)
        if not sessions:
            return "暂无会话。可用 /session_new 新建"
        active = self._sessions.active_session(chat_id)
        lines = []
        for item in sessions:
            sid = str(item.get("id", ""))
            title = str(item.get("title", "session"))
            mark = "*" if sid == active else " "
            lines.append(f"{mark} {sid[:8]} | {title} | {item.get('last_used_at', '')}")
        return "Copilot 会话列表(*为当前):\n" + "\n".join(lines)

    def session_new_text(self, chat_id: int, title: str | None = None) -> str:
        """新建会话并切换"""
        session_id = self._sessions.create_session(chat_id, title=title or "manual-new")
        return f"已新建并切换会话: {session_id}"

    def session_use_text(self, chat_id: int, session_id_prefix: str) -> str:
        """切换会话到指定 ID 前缀的会话"""
        session_id = self._sessions.set_active(chat_id, session_id_prefix)
        if session_id is None:
            return f"未找到会话: {session_id_prefix}"
        return f"已切换到会话: {session_id}"
