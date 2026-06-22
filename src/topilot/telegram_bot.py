from __future__ import annotations
"""Telegram 机器人接入层"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from html import escape

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest, NetworkError
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from topilot.config import Settings
from topilot.task_runner import TaskRunner

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

logger = logging.getLogger(__name__)


def _bot_commands() -> list[BotCommand]:
    """返回需要注册到 Telegram 菜单的命令"""

    return [
        BotCommand("start", "打开主菜单"),
        BotCommand("status", "查看状态与诊断"),
        BotCommand("model", "查看和切换模型"),
        BotCommand("sessions", "管理会话"),
        BotCommand("session_current", "查看当前会话"),
        BotCommand("session_new", "新建会话"),
        BotCommand("session_use", "按前缀切换会话"),
        BotCommand("whoami", "查看 chat id"),
    ]


def _is_allowed(settings: Settings, chat_id: int | None) -> bool:
    """判断当前 chat 是否在允许名单中"""

    if chat_id is None:
        return False
    if not settings.allowed_chat_ids:
        return True
    return chat_id in settings.allowed_chat_ids


def restricted(settings: Settings, handler: Handler) -> Handler:
    """为处理器添加 chat 白名单校验"""

    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not _is_allowed(settings, chat_id):
            logger.warning("未授权访问 chat_id=%s", chat_id)
            if update.effective_message:
                await update.effective_message.reply_text("当前用户未授权，请使用 /whoami 获取 chat id，并写入配置项 telegram.allowed_chat_ids")
            return
        await handler(update, context)

    return wrapped


def _preview_update_text(text: str | None, limit: int = 120) -> str:
    """压缩日志中的更新文本，便于定位普通文本消息是否进站"""

    if text is None:
        return "<none>"
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    if not normalized:
        return "<empty>"
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "..."


def _update_log_context(update: object | None) -> tuple[str, str, str, str]:
    """提取更新日志上下文，避免日志里只有一句“没反应”"""

    if not isinstance(update, Update):
        return ("<none>", "<none>", "<none>", "<none>")

    update_id = str(update.update_id)
    chat_id = str(update.effective_chat.id) if update.effective_chat else "<none>"
    message_id = str(update.effective_message.message_id) if update.effective_message else "<none>"

    if update.callback_query and update.callback_query.data:
        text = f"[callback] {update.callback_query.data}"
    elif update.effective_message:
        text = (
            update.effective_message.text
            or update.effective_message.caption
            or "<non-text>"
        )
    else:
        text = "<none>"
    return (update_id, chat_id, message_id, _preview_update_text(text))


def build_application(settings: Settings) -> Application:
    """构建并返回 Telegram Application 实例"""

    application: Application | None = None
    session_watch_tasks: dict[int, asyncio.Task[None]] = {}

    class TelegramLiveProgress:
        """Telegram 端流式展示实现"""

        def __init__(self, chat_id: int, title: str) -> None:
            self._chat_id = chat_id
            self._title = title
            self._progress_message: Message | None = None
            self._reply_message: Message | None = None
            self._reply_buffer = ""
            self._progress_lines: list[str] = []
            self._last_progress_render = ""
            self._last_progress_edit_at = 0.0
            self._progress_flush_task: asyncio.Task[None] | None = None
            self._reply_flush_task: asyncio.Task[None] | None = None
            self._last_reply_render = ""
            self._last_reply_edit_at = 0.0
            self._reply_started = False
            self._progress_supports_html = True
            self._closed = False

        async def start(self) -> "TelegramLiveProgress":
            """启动流式对象"""

            return self

        async def log(self, text: str) -> None:
            """接收并渲染过程日志"""

            normalized = text.strip()
            if not normalized or self._closed:
                return
            if self._should_skip_log(normalized):
                return
            if self._reply_started:
                await self._roll_to_next_round()
            merged = self._merge_progress_line(normalized)
            if merged and self._can_edit_progress_now():
                await self._flush_progress(force=True)
                return
            self._ensure_progress_flush_task()

        async def reply(self, text: str) -> None:
            """接收并渲染流式回复内容"""

            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            if normalized == "" or self._closed:
                return
            self._reply_started = True
            self._append_reply_chunk(normalized)
            if self._can_edit_reply_now():
                await self._flush_reply(force=True)
                return
            self._ensure_reply_flush_task()

        async def close(self, final_text: str | None = None, failed: bool = False) -> None:
            """结束流式会话并刷新最终显示"""

            if self._closed:
                return
            self._closed = True
            if final_text and final_text.strip():
                final_clean = final_text.replace("\r\n", "\n").replace("\r", "\n").strip()
                if final_clean != self._reply_text():
                    self._reply_buffer = final_clean
            if failed:
                self._progress_lines.append("执行失败")
            await self._flush_progress(force=True)
            await self._flush_reply(force=True)
            await self._cancel_task(self._progress_flush_task)
            await self._cancel_task(self._reply_flush_task)

        async def _roll_to_next_round(self) -> None:
            """当回复后再次出现过程事件时，切换到新的展示轮次"""

            await self._flush_progress(force=True)
            await self._flush_reply(force=True)
            await self._cancel_task(self._progress_flush_task)
            await self._cancel_task(self._reply_flush_task)
            self._progress_flush_task = None
            self._reply_flush_task = None
            self._progress_message = None
            self._reply_message = None
            self._progress_lines = []
            self._reply_buffer = ""
            self._last_progress_render = ""
            self._last_reply_render = ""
            self._last_progress_edit_at = 0.0
            self._last_reply_edit_at = 0.0
            self._reply_started = False

        def _render_progress_plain(self) -> str:
            state = "已完成" if self._closed else "进行中"
            lines = self._progress_lines[-12:]
            if not lines:
                lines = ["处理中..."]
            rendered_lines: list[str] = []
            for line in lines:
                parts = [part for part in line.splitlines() if part.strip()]
                if not parts:
                    continue
                rendered_lines.append(f"- {parts[0]}")
                rendered_lines.extend(f"  {part}" for part in parts[1:])
            body = "\n".join(rendered_lines) if rendered_lines else "- 处理中..."
            return f"[过程] {state}\n{body}"

        def _render_progress_html(self) -> str:
            state = "已完成" if self._closed else "进行中"
            lines = self._progress_lines[-12:]
            if not lines:
                lines = ["处理中..."]

            html_lines: list[str] = []
            for line in lines:
                parts = [part for part in line.splitlines() if part.strip()]
                if not parts:
                    continue
                headline = parts[0]
                html_lines.append(f"• {escape(headline, quote=False)}")
                detail_lines = parts[1:]
                if not detail_lines:
                    continue
                detail = "\n".join(escape(part, quote=False) for part in detail_lines)
                if self._should_use_expandable_quote(headline, detail_lines):
                    html_lines.append(f"<blockquote expandable>{detail}</blockquote>")
                else:
                    html_lines.append(f"<blockquote>{detail}</blockquote>")

            body = "\n".join(html_lines) if html_lines else "• 处理中..."
            return f"<b>过程</b> [{state}]\n{body}"

        def _should_use_expandable_quote(self, headline: str, detail_lines: list[str]) -> bool:
            if self._is_result_section(headline):
                return True
            joined = "\n".join(detail_lines)
            return len(joined) > 320 or len(detail_lines) > 6

        def _is_result_section(self, headline: str) -> bool:
            lowered = headline.lower()
            keywords = (
                "结果",
                "输出",
                "失败",
                "列表",
                "检索",
                "抓取",
                "子任务",
                "返回",
                "command=",
            )
            return any(keyword in lowered for keyword in keywords)

        def _render_reply(self) -> str:
            reply_text = self._reply_text()
            if not reply_text:
                return "..."
            return self._trim_tail(reply_text, 3200)

        def _reply_text(self) -> str:
            return self._reply_buffer.rstrip()

        def _append_reply_chunk(self, chunk: str) -> None:
            if not self._reply_buffer:
                self._reply_buffer = chunk
                return

            current = self._reply_buffer
            if chunk.startswith(current):
                self._reply_buffer = chunk
                return
            if current.endswith(chunk):
                return
            overlap = self._suffix_prefix_overlap(current, chunk)
            if overlap >= 6:
                self._reply_buffer += chunk[overlap:]
                return
            if self._looks_like_delta_chunk(chunk):
                self._reply_buffer += chunk
                return

            if current and not current.endswith("\n"):
                self._reply_buffer += "\n"
            self._reply_buffer += chunk

        def _suffix_prefix_overlap(self, left: str, right: str) -> int:
            max_len = min(len(left), len(right))
            for size in range(max_len, 0, -1):
                if left.endswith(right[:size]):
                    return size
            return 0

        def _looks_like_delta_chunk(self, chunk: str) -> bool:
            if "\n" in chunk:
                return False
            if len(chunk) <= 8:
                return True
            punctuation = set("，。！？；：、,.!?;:()[]{}<>+-=*/\\\"'`")
            if all(char in punctuation for char in chunk):
                return True
            return False

        def _trim_tail(self, text: str, limit: int) -> str:
            if len(text) <= limit:
                return text
            return "...(仅显示末尾)\n" + text[-limit:]

        def _can_edit_progress_now(self) -> bool:
            return (time.monotonic() - self._last_progress_edit_at) >= 1.0

        def _can_edit_reply_now(self) -> bool:
            return (time.monotonic() - self._last_reply_edit_at) >= 0.8

        def _ensure_progress_flush_task(self) -> None:
            if self._progress_flush_task is None or self._progress_flush_task.done():
                self._progress_flush_task = asyncio.create_task(self._delayed_flush_progress())

        def _ensure_reply_flush_task(self) -> None:
            if self._reply_flush_task is None or self._reply_flush_task.done():
                self._reply_flush_task = asyncio.create_task(self._delayed_flush_reply())

        async def _delayed_flush_progress(self) -> None:
            await asyncio.sleep(1.0)
            await self._flush_progress(force=True)

        async def _delayed_flush_reply(self) -> None:
            await asyncio.sleep(0.8)
            await self._flush_reply(force=True)

        async def _flush_progress(self, force: bool = False) -> None:
            if not self._progress_lines and not self._closed:
                return
            if not self._progress_lines and self._closed:
                return
            rendered = self._render_progress_plain()
            if self._progress_message is None:
                self._progress_message = await self._send_progress(rendered)
                self._last_progress_render = rendered
                self._last_progress_edit_at = time.monotonic()
                return
            if not force and not self._can_edit_progress_now():
                self._ensure_progress_flush_task()
                return
            if rendered == self._last_progress_render:
                return
            self._last_progress_render = rendered
            self._last_progress_edit_at = time.monotonic()
            await self._edit_progress(rendered)

        async def _flush_reply(self, force: bool = False) -> None:
            rendered = self._render_reply()
            if self._reply_message is None:
                if rendered == "...":
                    return
                self._reply_message = await self._send_raw(rendered)
                self._last_reply_render = rendered
                self._last_reply_edit_at = time.monotonic()
                return
            if not force and not self._can_edit_reply_now():
                self._ensure_reply_flush_task()
                return
            if rendered == self._last_reply_render:
                return
            self._last_reply_render = rendered
            self._last_reply_edit_at = time.monotonic()
            try:
                await self._reply_message.edit_text(rendered)
            except BadRequest as exc:
                if "Message is not modified" not in str(exc):
                    raise

        def _merge_progress_line(self, line: str) -> bool:
            if not self._progress_lines:
                self._progress_lines.append(line)
                return True
            last = self._progress_lines[-1]
            if last == line:
                self._progress_lines[-1] = f"{line} × 2"
                return True
            if last.startswith(f"{line} × "):
                count_text = last.split(" × ")[-1].strip()
                count = int(count_text) if count_text.isdigit() else 1
                self._progress_lines[-1] = f"{line} × {count + 1}"
                return True
            self._progress_lines.append(line)
            if len(self._progress_lines) > 60:
                self._progress_lines = self._progress_lines[-60:]
            return True

        def _should_skip_log(self, line: str) -> bool:
            lowered = line.lower()
            noisy = (
                "[session.tools_updated]",
                "[user.message]",
                "report_intent",
                "[subagent.completed]",
            )
            return any(flag in lowered for flag in noisy)

        async def _send_raw(self, text: str) -> Message:
            assert application is not None
            return await application.bot.send_message(chat_id=self._chat_id, text=text)

        async def _send_progress(self, plain_text: str) -> Message:
            assert application is not None
            if self._progress_supports_html:
                try:
                    return await application.bot.send_message(
                        chat_id=self._chat_id,
                        text=self._render_progress_html(),
                        parse_mode="HTML",
                    )
                except BadRequest as exc:
                    if "can't parse entities" not in str(exc).lower():
                        raise
                    self._progress_supports_html = False
            return await application.bot.send_message(chat_id=self._chat_id, text=plain_text)

        async def _edit_progress(self, plain_text: str) -> None:
            if self._progress_message is None:
                return
            if self._progress_supports_html:
                try:
                    await self._progress_message.edit_text(self._render_progress_html(), parse_mode="HTML")
                    return
                except BadRequest as exc:
                    message = str(exc)
                    if "Message is not modified" in message:
                        return
                    if "can't parse entities" not in message.lower():
                        raise
                    self._progress_supports_html = False
            try:
                await self._progress_message.edit_text(plain_text)
            except BadRequest as exc:
                if "Message is not modified" not in str(exc):
                    raise

        async def _cancel_task(self, task: asyncio.Task[None] | None) -> None:
            if task is None or task.done():
                return
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def send_message(chat_id: int, text: str) -> None:
        if application is None:
            return
        for chunk in _chunk_text(text):
            await application.bot.send_message(chat_id=chat_id, text=chunk)

    async def open_live_progress(chat_id: int, title: str) -> TelegramLiveProgress:
        progress = TelegramLiveProgress(chat_id, title)
        return await progress.start()

    runner = TaskRunner(settings, send_message, open_live_progress=open_live_progress)

    async def on_startup(app: Application) -> None:
        await runner.start()
        app.bot_data["runner"] = runner
        try:
            await app.bot.set_my_commands(_bot_commands())
            logger.info("Telegram Bot 命令菜单注册完成")
        except Exception as exc:
            logger.warning("Telegram Bot 命令菜单注册失败: %s", exc)
        logger.info("Telegram application 启动完成")

    async def trace_incoming_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not isinstance(update, Update):
            return
        if not update.effective_message or not update.effective_chat:
            return
        update_id, chat_id, message_id, text_preview = _update_log_context(update)
        logger.info(
            "收到 Telegram 更新 update_id=%s chat_id=%s message_id=%s text=%s",
            update_id,
            chat_id,
            message_id,
            text_preview,
        )

    async def application_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        error = context.error
        update_id, chat_id, message_id, text_preview = _update_log_context(update)
        if update is None and isinstance(error, NetworkError):
            if application is not None:
                application.bot_data["telegram_restart_requested"] = True
                logger.warning("Telegram polling 网络异常，准备重建应用: %s", error)
                application.stop_running()
            return
        if error is None:
            logger.error(
                "Telegram 更新处理失败 update_id=%s chat_id=%s message_id=%s payload=%s",
                update_id,
                chat_id,
                message_id,
                text_preview,
            )
            return
        logger.error(
            "Telegram 更新处理失败 update_id=%s chat_id=%s message_id=%s payload=%s",
            update_id,
            chat_id,
            message_id,
            text_preview,
            exc_info=(type(error), error, error.__traceback__),
        )

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text, keyboard = _render_main_menu()
        await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat or not update.effective_user:
            return
        await update.effective_message.reply_text(
            _whoami_text(update),
            reply_markup=InlineKeyboardMarkup(_render_back_to_main_keyboard()),
        )

    async def session_current_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        text, keyboard = _render_session_current_panel(runner.session_current_text(update.effective_chat.id))
        await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        await _send_session_menu(update.effective_message, update.effective_chat.id, page=0)

    async def session_new_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        title = " ".join(context.args).strip() if context.args else None
        await update.effective_message.reply_text(
            runner.session_new_text(update.effective_chat.id, title),
            reply_markup=InlineKeyboardMarkup(_render_session_action_keyboard()),
        )

    async def session_use_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        if not context.args:
            await update.effective_message.reply_text(
                "请提供会话 ID 前缀",
                reply_markup=InlineKeyboardMarkup(_render_session_action_keyboard()),
            )
            return
        await update.effective_message.reply_text(
            runner.session_use_text(update.effective_chat.id, context.args[0]),
            reply_markup=InlineKeyboardMarkup(_render_session_action_keyboard()),
        )

    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        text, keyboard = _render_status_panel(runner.status_text(update.effective_chat.id))
        await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat or not update.effective_message.text:
            return
        update_id, chat_id, message_id, text_preview = _update_log_context(update)
        logger.info(
            "收到文本消息 update_id=%s chat_id=%s message_id=%s text=%s",
            update_id,
            chat_id,
            message_id,
            text_preview,
        )
        await runner.submit(update.effective_chat.id, update.effective_message.text)

    async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """展示模型选择按钮"""
        if not update.effective_message or not update.effective_chat:
            return
        chat_id = update.effective_chat.id
        models = _normalize_model_list(runner.list_models())
        if not models:
            text, keyboard = _render_status_panel("暂时无法获取可用模型列表，当前无法修改模型")
            await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return
        current = runner.current_model(chat_id)
        text, keyboard = _render_model_menu(models, current)
        await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def model_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理模型选择按钮回调"""
        query = update.callback_query
        if not query or not query.data:
            return
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not chat_id or not _is_allowed(settings, chat_id):
            await query.answer("未授权", show_alert=True)
            return
        model = _callback_payload(query.data, "model_sel:")
        if not model:
            await query.answer()
            return
        if model not in _normalize_model_list(runner.list_models()):
            await query.answer("模型不存在", show_alert=True)
            return
        runner.set_model(chat_id, model)
        await query.answer(f"已切换: {model}")
        text, keyboard = _render_model_menu(_normalize_model_list(runner.list_models()), model, prefix=f"已切换: {model}")
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            pass

    async def navigation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not query.data:
            return
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not chat_id or not _is_allowed(settings, chat_id):
            await query.answer("未授权", show_alert=True)
            return

        action = _callback_payload(query.data, "nav:")
        await query.answer()

        if action == "main":
            text, keyboard = _render_main_menu()
        elif action == "status":
            text, keyboard = _render_status_panel(runner.status_text(chat_id))
        elif action == "diagnostic":
            text, keyboard = _render_diagnostic_panel(runner.llm_diagnostic_text(chat_id))
        elif action == "model":
            models = _normalize_model_list(runner.list_models())
            if not models:
                text, keyboard = _render_status_panel("暂时无法获取可用模型列表，当前无法修改模型")
            else:
                text, keyboard = _render_model_menu(models, runner.current_model(chat_id))
        elif action == "sessions":
            await _edit_session_menu(query, chat_id, page=0)
            return
        elif action == "session_current":
            text, keyboard = _render_session_current_panel(runner.session_current_text(chat_id))
        elif action == "session_new":
            text = runner.session_new_text(chat_id)
            keyboard = _render_session_action_keyboard()
        elif action == "whoami":
            text, keyboard = _whoami_text(update), _render_back_to_main_keyboard()
        else:
            text, keyboard = _render_main_menu()

        await query.edit_message_text(_trim_telegram_text(text), reply_markup=InlineKeyboardMarkup(keyboard))

    async def session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not query.data:
            return
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not chat_id or not _is_allowed(settings, chat_id):
            await query.answer("未授权", show_alert=True)
            return

        data = query.data
        await query.answer()

        if data.startswith("smenu:"):
            await _edit_session_menu(query, chat_id, page=_callback_page(data))
            return

        if data.startswith("sopen:"):
            sid = _callback_payload(data, "sopen:")
            await _edit_session_detail(query, chat_id, sid)
            return

        if data.startswith("suse:"):
            sid = _callback_payload(data, "suse:")
            text = runner.takeover_session(chat_id, sid)
            try:
                await _edit_session_detail(query, chat_id, sid, prefix=f"✓ {text}")
            except Exception:
                pass

            payload = runner.session_live_payload(chat_id, sid)
            history_msg = await application.bot.send_message(chat_id=chat_id, text=_trim_telegram_text(str(payload.get("text", ""))))

            await _stop_session_watch(chat_id)
            if bool(payload.get("running", False)):
                session_watch_tasks[chat_id] = asyncio.create_task(_watch_session_live(chat_id, sid, history_msg.chat_id, history_msg.message_id))
            return

        if data.startswith("shis:"):
            sid = _callback_payload(data, "shis:")
            history_text = runner.session_history_text(chat_id, sid)
            _, keyboard_buttons = _render_session_history(history_text, sid)
            keyboard = InlineKeyboardMarkup(keyboard_buttons)
            await query.edit_message_text(history_text, reply_markup=keyboard)
            return

        if data.startswith("sdel:"):
            sid = _callback_payload(data, "sdel:")
            await _edit_session_delete_confirm(query, chat_id, sid)
            return

        if data.startswith("sdelok:"):
            sid = _callback_payload(data, "sdelok:")
            text = runner.delete_session(chat_id, sid, delete_local=True)
            await _edit_session_menu(query, chat_id, page=0, prefix=text)
            return

    async def _send_session_menu(message: Message, chat_id: int, page: int = 0) -> None:
        items = runner.session_menu_items(chat_id, limit=30)
        text, keyboard = _render_session_menu(items, page)
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def _edit_session_menu(query, chat_id: int, page: int = 0, prefix: str | None = None) -> None:
        items = runner.session_menu_items(chat_id, limit=30)
        text, keyboard = _render_session_menu(items, page)
        if prefix:
            text = f"{prefix}\n\n{text}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def _edit_session_detail(query, chat_id: int, session_id: str, prefix: str | None = None) -> None:
        text, keyboard_buttons = _render_session_detail(runner.session_detail_text(chat_id, session_id), session_id, prefix=prefix)
        keyboard = InlineKeyboardMarkup(keyboard_buttons)
        await query.edit_message_text(text, reply_markup=keyboard)

    async def _edit_session_delete_confirm(query, chat_id: int, session_id: str) -> None:
        text, keyboard_buttons = _render_session_delete_confirm(runner.session_detail_text(chat_id, session_id), session_id)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard_buttons))

    async def _stop_session_watch(chat_id: int) -> None:
        task = session_watch_tasks.pop(chat_id, None)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _watch_session_live(chat_id: int, session_id: str, message_chat_id: int, message_id: int) -> None:
        """轮询会话历史，运行中时自动刷新同一条消息"""
        interval = max(1.0, min(settings.session_watch_interval_seconds, 15.0))
        last_signature = ""
        stable_rounds = 0
        try:
            for _ in range(150):
                payload = runner.session_live_payload(chat_id, session_id)
                text = _trim_telegram_text(str(payload.get("text", "")))
                signature = str(payload.get("signature", ""))
                running = bool(payload.get("running", False))

                if signature != last_signature:
                    last_signature = signature
                    stable_rounds = 0
                    try:
                        await application.bot.edit_message_text(
                            chat_id=message_chat_id,
                            message_id=message_id,
                            text=text,
                        )
                    except BadRequest as exc:
                        if "Message is not modified" not in str(exc):
                            raise
                else:
                    stable_rounds += 1

                if not running and stable_rounds >= 3:
                    final_text = _trim_telegram_text(text + "\n\n会话已停止，自动追踪结束")
                    try:
                        await application.bot.edit_message_text(
                            chat_id=message_chat_id,
                            message_id=message_id,
                            text=final_text,
                        )
                    except BadRequest as exc:
                        if "Message is not modified" not in str(exc):
                            raise
                    break

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    builder = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .get_updates_connect_timeout(10.0)
        .get_updates_read_timeout(45.0)
        .get_updates_write_timeout(10.0)
        .get_updates_pool_timeout(10.0)
    )
    if settings.telegram_proxy_url:
        builder = builder.proxy(settings.telegram_proxy_url).get_updates_proxy(settings.telegram_proxy_url)

    application = builder.post_init(on_startup).build()

    application.add_handler(MessageHandler(filters.ALL, trace_incoming_message), group=-1)
    application.add_error_handler(application_error_handler)
    application.add_handler(CommandHandler("whoami", whoami_command))
    application.add_handler(CommandHandler("session_current", restricted(settings, session_current_command)))
    application.add_handler(CommandHandler("sessions", restricted(settings, sessions_command)))
    application.add_handler(CommandHandler("session_new", restricted(settings, session_new_command)))
    application.add_handler(CommandHandler("session_use", restricted(settings, session_use_command)))
    application.add_handler(CommandHandler("model", restricted(settings, model_command)))
    application.add_handler(CommandHandler("start", restricted(settings, start_command)))
    application.add_handler(CommandHandler("status", restricted(settings, status_command)))
    application.add_handler(CallbackQueryHandler(model_select_callback, pattern=r"^model_sel:"))
    application.add_handler(CallbackQueryHandler(navigation_callback, pattern=r"^nav:"))
    application.add_handler(CallbackQueryHandler(session_callback, pattern=r"^(smenu:|sopen:|suse:|shis:|sdel:|sdelok:)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, restricted(settings, text_message)))

    return application


def _chunk_text(text: str, limit: int = 3500) -> list[str]:
    """按 Telegram 消息长度上限切分文本"""

    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]
    return chunks


def _render_main_menu() -> tuple[str, list[list[InlineKeyboardButton]]]:
    """渲染主菜单文本和按钮"""

    text = "Topilot 主菜单\n直接发送文本即可开始对话。"
    keyboard = [
        [
            InlineKeyboardButton("状态与诊断", callback_data="nav:status"),
            InlineKeyboardButton("模型切换", callback_data="nav:model"),
        ],
        [
            InlineKeyboardButton("会话管理", callback_data="nav:sessions"),
            InlineKeyboardButton("当前会话", callback_data="nav:session_current"),
        ],
        [
            InlineKeyboardButton("新建会话", callback_data="nav:session_new"),
            InlineKeyboardButton("我的 ID", callback_data="nav:whoami"),
        ],
    ]
    return text, keyboard


def _render_status_panel(status_text: str) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """渲染状态摘要和常用操作按钮"""

    keyboard = [
        [
            InlineKeyboardButton("后端诊断", callback_data="nav:diagnostic"),
            InlineKeyboardButton("模型切换", callback_data="nav:model"),
        ],
        [
            InlineKeyboardButton("会话管理", callback_data="nav:sessions"),
            InlineKeyboardButton("当前会话", callback_data="nav:session_current"),
        ],
        [InlineKeyboardButton("主菜单", callback_data="nav:main")],
    ]
    return status_text, keyboard


def _render_diagnostic_panel(diagnostic_text: str) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """渲染 Copilot 后端诊断面板"""

    keyboard = [
        [InlineKeyboardButton("刷新诊断", callback_data="nav:diagnostic")],
        [
            InlineKeyboardButton("状态摘要", callback_data="nav:status"),
            InlineKeyboardButton("主菜单", callback_data="nav:main"),
        ],
    ]
    return diagnostic_text, keyboard


def _render_session_current_panel(text: str) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """渲染当前会话摘要和快捷按钮"""

    keyboard = [
        [
            InlineKeyboardButton("会话管理", callback_data="nav:sessions"),
            InlineKeyboardButton("新建会话", callback_data="nav:session_new"),
        ],
        [
            InlineKeyboardButton("模型切换", callback_data="nav:model"),
            InlineKeyboardButton("状态与诊断", callback_data="nav:status"),
        ],
        [InlineKeyboardButton("主菜单", callback_data="nav:main")],
    ]
    return text, keyboard


def _render_session_action_keyboard() -> list[list[InlineKeyboardButton]]:
    """渲染会话操作后的快捷按钮"""

    return [
        [
            InlineKeyboardButton("会话管理", callback_data="nav:sessions"),
            InlineKeyboardButton("当前会话", callback_data="nav:session_current"),
        ],
        [InlineKeyboardButton("主菜单", callback_data="nav:main")],
    ]


def _render_back_to_main_keyboard() -> list[list[InlineKeyboardButton]]:
    """渲染返回主菜单按钮"""

    return [[InlineKeyboardButton("主菜单", callback_data="nav:main")]]


def _whoami_text(update: Update) -> str:
    """渲染当前 Telegram 身份信息"""

    chat_id = update.effective_chat.id if update.effective_chat else "<none>"
    user_id = update.effective_user.id if update.effective_user else "<none>"
    username = update.effective_user.username if update.effective_user and update.effective_user.username else "<none>"
    return f"chat_id: {chat_id}\nuser_id: {user_id}\nusername: {username}"


def _build_model_keyboard(models: list[str], current: str) -> list[list[InlineKeyboardButton]]:
    """构建模型选择内联键盘（2列布局，当前模型标 ✓）"""
    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for model in _normalize_model_list(models):
        label = f"✓ {model}" if model == current else model
        row.append(InlineKeyboardButton(label, callback_data=f"model_sel:{model}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return keyboard


def _render_model_menu(models: list[str], current: str, prefix: str | None = None) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """渲染模型选择文本和按钮"""

    normalized = _normalize_model_list(models)
    text = f"当前模型: {current}\n请选择模型:"
    if prefix:
        text = f"{prefix}\n\n{text}"
    keyboard = _build_model_keyboard(normalized, current)
    keyboard.extend(
        [
            [
                InlineKeyboardButton("状态与诊断", callback_data="nav:status"),
                InlineKeyboardButton("会话管理", callback_data="nav:sessions"),
            ],
            [InlineKeyboardButton("主菜单", callback_data="nav:main")],
        ]
    )
    return text, keyboard


def _normalize_model_list(models: list[str]) -> list[str]:
    """去重并清理模型列表，保证按钮和合法性校验口径一致"""

    seen: set[str] = set()
    result: list[str] = []
    for model in models:
        trimmed = str(model).strip()
        if not trimmed or trimmed in seen:
            continue
        seen.add(trimmed)
        result.append(trimmed)
    return result


def _trim_telegram_text(text: str, limit: int = 3500) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _render_session_menu(items: list[dict], page: int, page_size: int = 6) -> tuple[str, list[list[InlineKeyboardButton]]]:
    total = len(items)
    if total == 0:
        return (
            "未发现可管理会话",
            [
                [
                    InlineKeyboardButton("刷新", callback_data="smenu:0"),
                    InlineKeyboardButton("新建会话", callback_data="nav:session_new"),
                ],
                [InlineKeyboardButton("主菜单", callback_data="nav:main")],
            ],
        )

    max_page = max((total - 1) // page_size, 0)
    page = max(0, min(page, max_page))
    start = page * page_size
    current_items = items[start : start + page_size]

    lines = [f"会话管理 第 {page + 1}/{max_page + 1} 页"]
    keyboard: list[list[InlineKeyboardButton]] = []

    for item in current_items:
        sid = str(item.get("id", ""))
        short_sid = sid[:8]
        title = _shorten_menu_text(str(item.get("title") or "session"), 18)
        model = str(item.get("model") or "unknown")
        source = str(item.get("source") or "saved")
        running = "🟢" if item.get("running") else "⚪"
        active = "⭐" if item.get("active") else ""
        lines.append(f"{running}{active} {short_sid} | {title} | {model} | {source}")
        keyboard.append([InlineKeyboardButton(f"打开 {short_sid} {title}", callback_data=f"sopen:{sid}")])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton("上一页", callback_data=f"smenu:{page - 1}"))
    nav.append(InlineKeyboardButton("刷新", callback_data=f"smenu:{page}"))
    if page < max_page:
        nav.append(InlineKeyboardButton("下一页", callback_data=f"smenu:{page + 1}"))
    keyboard.append(nav)
    keyboard.append(
        [
            InlineKeyboardButton("新建会话", callback_data="nav:session_new"),
            InlineKeyboardButton("当前会话", callback_data="nav:session_current"),
        ]
    )
    keyboard.append([InlineKeyboardButton("主菜单", callback_data="nav:main")])

    return "\n".join(lines), keyboard


def _render_session_detail(detail_text: str, session_id: str, prefix: str | None = None) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """渲染会话详情页文本和按钮"""

    text = detail_text
    if prefix:
        text = f"{prefix}\n\n{text}"
    keyboard = [
        [InlineKeyboardButton("接管会话", callback_data=f"suse:{session_id}")],
        [InlineKeyboardButton("查看历史", callback_data=f"shis:{session_id}")],
        [InlineKeyboardButton("刷新详情", callback_data=f"sopen:{session_id}")],
        [InlineKeyboardButton("删除会话", callback_data=f"sdel:{session_id}")],
        [InlineKeyboardButton("返回列表", callback_data="smenu:0")],
        [InlineKeyboardButton("主菜单", callback_data="nav:main")],
    ]
    return text, keyboard


def _render_session_history(history_text: str, session_id: str) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """渲染会话历史页文本和按钮"""

    keyboard = [
        [InlineKeyboardButton("刷新历史", callback_data=f"shis:{session_id}")],
        [InlineKeyboardButton("返回详情", callback_data=f"sopen:{session_id}")],
        [InlineKeyboardButton("返回列表", callback_data="smenu:0")],
        [InlineKeyboardButton("主菜单", callback_data="nav:main")],
    ]
    return history_text, keyboard


def _render_session_delete_confirm(detail_text: str, session_id: str) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """渲染删除确认页，避免误触直接删除"""

    keyboard = [
        [InlineKeyboardButton("确认删除", callback_data=f"sdelok:{session_id}")],
        [InlineKeyboardButton("取消", callback_data=f"sopen:{session_id}")],
        [InlineKeyboardButton("返回列表", callback_data="smenu:0")],
        [InlineKeyboardButton("主菜单", callback_data="nav:main")],
    ]
    return f"确认删除该会话？\n\n{detail_text}", keyboard


def _callback_payload(data: str, prefix: str) -> str:
    """从回调数据中提取 payload"""

    return data[len(prefix):].strip() if data.startswith(prefix) else ""


def _callback_page(data: str) -> int:
    """解析会话菜单页码，非法或负数统一回到第 0 页"""

    page_text = _callback_payload(data, "smenu:")
    if not page_text.isdigit():
        return 0
    return max(0, int(page_text))


def _shorten_menu_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "..."
