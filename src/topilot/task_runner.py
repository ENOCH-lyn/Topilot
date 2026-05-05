from __future__ import annotations
"""对话编排模块"""

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from topilot.agent import AssistantPlanner
from topilot.copilot_sessions import CopilotSessionInfo, CopilotSessionInspector
from topilot.config import Settings
from topilot.conversation_store import ConversationStore
from topilot.session_store import SessionStore

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
        self._inspector = CopilotSessionInspector()
        # 启动后会被实时结果覆盖
        self._cached_models: list[str] = list(settings.copilot_available_models)
        self._discovered_sessions: dict[str, CopilotSessionInfo] = {}

    async def start(self) -> None:
        """启动时拉取实时模型列表并缓存"""
        self._cached_models = await self._planner.fetch_available_models()
        logger.info("可用模型: %s", self._cached_models)

    def refresh_discovered_sessions(self, limit: int = 40) -> list[dict]:
        """刷新并返回本机可发现的 Copilot 会话"""

        infos = self._inspector.list_sessions(limit=limit)
        self._discovered_sessions = {item.session_id: item for item in infos}
        result: list[dict] = []
        for item in infos:
            result.append(
                {
                    "id": item.session_id,
                    "title": item.summary or "copilot-session",
                    "cwd": item.cwd,
                    "model": item.model,
                    "running": item.running,
                    "last_event_at": item.last_event_at,
                    "source": "local",
                }
            )
        return result

    def session_menu_items(self, chat_id: int, limit: int = 20) -> list[dict]:
        """返回会话管理菜单项（已保存 + 本机发现）"""

        discovered = self.refresh_discovered_sessions(limit=40)
        discovered_map = {item["id"]: item for item in discovered}
        stored_items = self._sessions.list_sessions(chat_id, limit=100)

        merged: list[dict] = []
        for item in stored_items:
            sid = str(item.get("id", ""))
            external = discovered_map.get(sid, {})
            merged.append(
                {
                    "id": sid,
                    "title": str(item.get("title", "session")),
                    "cwd": item.get("cwd") or external.get("cwd"),
                    "model": item.get("model") or external.get("model"),
                    "running": bool(item.get("running") if "running" in item else external.get("running", False)),
                    "last_event_at": item.get("last_event_at") or external.get("last_event_at") or item.get("last_used_at"),
                    "stored": True,
                    "source": item.get("source") or external.get("source", "saved"),
                }
            )

        stored_ids = {entry["id"] for entry in merged}
        for item in discovered:
            sid = str(item.get("id", ""))
            if sid in stored_ids:
                continue
            merged.append(
                {
                    "id": sid,
                    "title": str(item.get("title") or "copilot-session"),
                    "cwd": item.get("cwd"),
                    "model": item.get("model"),
                    "running": bool(item.get("running", False)),
                    "last_event_at": item.get("last_event_at"),
                    "stored": False,
                    "source": "local",
                }
            )

        merged.sort(key=lambda x: str(x.get("last_event_at") or ""), reverse=True)
        active = self._sessions.active_session(chat_id)
        for item in merged:
            item["active"] = item["id"] == active
        return merged[:limit]

    def takeover_session(self, chat_id: int, session_id: str) -> str:
        """接管指定会话并切换为当前会话"""

        info = self._discovered_sessions.get(session_id) or self._inspector.get_session(session_id)
        if info:
            self._sessions.upsert_session(
                chat_id,
                session_id,
                title=info.summary or "adopted-session",
                cwd=info.cwd,
                model=info.model,
                source="local",
                last_event_at=info.last_event_at,
                running=info.running,
            )
            if info.model:
                self._sessions.set_model(chat_id, info.model)
        chosen = self._sessions.set_active(chat_id, session_id)
        if not chosen:
            return "未找到该会话"
        return f"已接管会话: {chosen}"

    def delete_session(self, chat_id: int, session_id: str, delete_local: bool = True) -> str:
        """删除会话（可选删除本地 session-state）"""

        removed_store = self._sessions.delete_session(chat_id, session_id)
        removed_local = False
        if delete_local:
            try:
                removed_local = self._inspector.delete_session(session_id)
            except Exception:
                removed_local = False

        if removed_store or removed_local:
            self._discovered_sessions.pop(session_id, None)
            return "会话已删除"
        return "会话不存在或无法删除"

    def session_detail_text(self, chat_id: int, session_id: str) -> str:
        """返回会话详情文本"""

        info = self._inspector.get_session(session_id)
        stored = self._sessions.get_session(chat_id, session_id)
        model = (info.model if info else None) or (stored.get("model") if stored else None) or self.current_model(chat_id)
        cwd = (info.cwd if info else None) or (stored.get("cwd") if stored else None) or self._settings.workspace_root.as_posix()
        running = info.running if info else bool(stored.get("running") if stored else False)
        stamp = (info.last_event_at if info else None) or (stored.get("last_event_at") if stored else None) or "-"
        active = self._sessions.active_session(chat_id)
        return (
            f"会话: {session_id}\n"
            f"状态: {'运行中' if running else '空闲'}\n"
            f"模型: {model}\n"
            f"工作区: {cwd}\n"
            f"最后事件: {stamp}\n"
            f"当前激活: {'是' if active == session_id else '否'}"
        )

    def session_history_text(self, chat_id: int, session_id: str) -> str:
        """返回会话历史摘要文本"""

        info = self._inspector.get_session(session_id)
        if not info:
            return "未找到该会话的历史"
        head = self.session_detail_text(chat_id, session_id)
        lines = info.history_lines or ["暂无可展示历史"]
        body = "\n".join(f"- {line}" for line in lines[-12:])
        return f"{head}\n\n最近历史:\n{body}"

    def session_live_payload(self, chat_id: int, session_id: str) -> dict:
        """返回会话实时展示载荷

        用于 bot 侧轮询刷新运行中会话输出
        """

        info = self._inspector.get_session(session_id)
        if not info:
            return {
                "exists": False,
                "running": False,
                "text": "会话不存在或已被删除",
                "signature": f"missing:{session_id}",
            }

        head = self.session_detail_text(chat_id, session_id)
        lines = info.history_lines or ["暂无可展示历史"]
        tail_lines = lines[-10:]
        body = "\n".join(f"- {line}" for line in tail_lines)
        text = f"{head}\n\n最近历史:\n{body}"
        signature = f"{info.last_event_at}|{info.running}|{'|'.join(tail_lines[-3:])}"
        return {
            "exists": True,
            "running": info.running,
            "text": text,
            "signature": signature,
            "last_event_at": info.last_event_at,
        }

    async def submit(self, chat_id: int, instruction: str) -> None:
        """处理一次用户请求并回传结果"""

        logger.info("收到请求 chat_id=%s instruction_len=%s", chat_id, len(instruction.strip()))

        history = self._conversation.recent(chat_id)
        active_session_id = self._sessions.ensure_active_session(chat_id)
        self._sessions.touch(chat_id, active_session_id)

        live_progress = await self._start_live_progress(chat_id, instruction)
        model = self._sessions.active_model(chat_id)
        active_session_meta = self._sessions.get_session(chat_id, active_session_id) or {}
        workspace_dir = str(active_session_meta.get("cwd", "")).strip() or None
        try:
            plan = await self._planner.plan(
                active_session_id,
                history,
                instruction,
                model=model,
                workspace_dir=workspace_dir,
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
        session_meta = self._sessions.get_session(chat_id, session_id) or {}
        model = self.current_model(chat_id)
        source = str(session_meta.get("source") or "bot")
        running = bool(session_meta.get("running", False))
        workspace = str(session_meta.get("cwd") or self._settings.workspace_root.as_posix())
        title = str(session_meta.get("title") or "session")
        last_event_at = str(session_meta.get("last_event_at") or session_meta.get("last_used_at") or "-")
        return (
            f"后端状态: {self._planner.llm_status_text(model)}\n"
            f"当前会话: {session_id}\n"
            f"会话标题: {title}\n"
            f"会话来源: {source}\n"
            f"会话状态: {'运行中' if running else '空闲'}\n"
            f"当前模型: {model}\n"
            f"工作区: {workspace}\n"
            f"最近活动: {last_event_at}"
        )

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
            needle = session_id_prefix.strip().lower()
            for item in self.session_menu_items(chat_id, limit=100):
                sid = str(item.get("id", ""))
                if sid.lower().startswith(needle):
                    return self.takeover_session(chat_id, sid)
            return f"未找到会话: {session_id_prefix}"
        return f"已切换到会话: {session_id}"
