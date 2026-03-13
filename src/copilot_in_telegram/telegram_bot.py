from __future__ import annotations
"""Telegram 机器人接入层"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from copilot_in_telegram.config import Settings
from copilot_in_telegram.task_runner import TaskRunner

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

logger = logging.getLogger(__name__)


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
                await update.effective_message.reply_text("当前用户未授权。请使用 /whoami 获取 chat id，再把将其加入到 TELEGRAM_ALLOWED_CHAT_IDS中")
            return
        await handler(update, context)

    return wrapped


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
            merged = self._merge_progress_line(normalized)
            if merged and self._can_edit_progress_now():
                await self._flush_progress(force=True)
                return
            self._ensure_progress_flush_task()

        async def reply(self, text: str) -> None:
            """接收并渲染流式回复内容"""

            normalized = text.strip()
            if not normalized or self._closed:
                return
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
                final_clean = final_text.strip()
                if final_clean != self._reply_text():
                    self._reply_buffer = final_clean
            if failed:
                self._progress_lines.append("执行失败")
            await self._flush_progress(force=True)
            await self._flush_reply(force=True)
            await self._cancel_task(self._progress_flush_task)
            await self._cancel_task(self._reply_flush_task)

        def _render_progress(self) -> str:
            state = "已完成" if self._closed else "进行中"
            lines = self._progress_lines[-12:]
            if not lines:
                lines = ["处理中..."]
            body = "\n".join(f"- {line}" for line in lines)
            return f"[过程] {state}\n{body}"

        def _render_reply(self) -> str:
            reply_text = self._reply_text()
            if not reply_text:
                return "..."
            return self._trim_tail(reply_text, 3200)

        def _reply_text(self) -> str:
            return self._reply_buffer.strip()

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
            if self._looks_like_delta_chunk(chunk):
                self._reply_buffer += chunk
                return

            if current and not current.endswith("\n"):
                self._reply_buffer += "\n"
            self._reply_buffer += chunk

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
            if self._progress_message is None:
                self._progress_message = await self._send_raw(self._render_progress())
                return
            if not force and not self._can_edit_progress_now():
                self._ensure_progress_flush_task()
                return
            rendered = self._render_progress()
            if rendered == self._last_progress_render:
                return
            self._last_progress_render = rendered
            self._last_progress_edit_at = time.monotonic()
            try:
                await self._progress_message.edit_text(rendered)
            except BadRequest as exc:
                if "Message is not modified" not in str(exc):
                    raise

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
        logger.info("Telegram application 启动完成")

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "可用命令（Copilot 对话模式）:\n"
            "/whoami\n"
            "/llm\n"
            "/session_current\n"
            "/sessions\n"
            "/session_new [title]\n"
            "/session_use <session_id前缀>\n"
            "/model\n"
            "/status\n"
            "也可直接发送文本"
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "帮助信息（Copilot 对话模式）:\n"
            "/whoami\n"
            "/llm\n"
            "/session_current\n"
            "/sessions\n"
            "/session_new [title]\n"
            "/session_use <session_id前缀>\n"
            "/model\n"
            "/status\n"
            "也可直接发送文本"
        )

    async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat or not update.effective_user:
            return
        username = update.effective_user.username or "<none>"
        await update.effective_message.reply_text(
            f"chat_id: {update.effective_chat.id}\n"
            f"user_id: {update.effective_user.id}\n"
            f"username: {username}"
        )

    async def llm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        await update.effective_message.reply_text(f"后端状态: {runner.llm_status_text(update.effective_chat.id)}")

    async def session_current_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        await update.effective_message.reply_text(runner.session_current_text(update.effective_chat.id))

    async def sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        await _send_session_menu(update.effective_message, update.effective_chat.id, page=0)

    async def session_new_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        title = " ".join(context.args).strip() if context.args else None
        await update.effective_message.reply_text(runner.session_new_text(update.effective_chat.id, title))

    async def session_use_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        if not context.args:
            await update.effective_message.reply_text("请提供会话 ID 前缀")
            return
        await update.effective_message.reply_text(runner.session_use_text(update.effective_chat.id, context.args[0]))

    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        await update.effective_message.reply_text(runner.status_text(update.effective_chat.id))

    async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat or not update.effective_message.text:
            return
        logger.info("收到文本消息 chat_id=%s", update.effective_chat.id)
        await runner.submit(update.effective_chat.id, update.effective_message.text)

    async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """展示模型选择按钮"""
        if not update.effective_message or not update.effective_chat:
            return
        chat_id = update.effective_chat.id
        models = runner.list_models()
        if not models:
            await update.effective_message.reply_text("暂时无法获取可用模型列表，当前无法修改模型")
            return
        current = runner.current_model(chat_id)
        keyboard = _build_model_keyboard(models, current)
        await update.effective_message.reply_text(
            f"当前模型: {current}\n请选择模型:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def model_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理模型选择按钮回调"""
        query = update.callback_query
        if not query or not query.data:
            return
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not chat_id or not _is_allowed(settings, chat_id):
            await query.answer("未授权", show_alert=True)
            return
        model = query.data[len("model_sel:"):]
        if not model:
            await query.answer()
            return
        if model not in runner.list_models():
            await query.answer("模型不存在", show_alert=True)
            return
        runner.set_model(chat_id, model)
        await query.answer(f"已切换: {model}")
        try:
            await query.edit_message_text(f"✓ 当前模型: {model}")
        except Exception:
            pass

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
            page_text = data.split(":", 1)[1]
            page = int(page_text) if page_text.isdigit() else 0
            await _edit_session_menu(query, chat_id, page=page)
            return

        if data.startswith("sopen:"):
            sid = data.split(":", 1)[1]
            await _edit_session_detail(query, chat_id, sid)
            return

        if data.startswith("suse:"):
            sid = data.split(":", 1)[1]
            text = runner.takeover_session(chat_id, sid)
            try:
                await query.edit_message_text(f"✓ {text}")
            except Exception:
                pass

            payload = runner.session_live_payload(chat_id, sid)
            history_msg = await application.bot.send_message(chat_id=chat_id, text=_trim_telegram_text(str(payload.get("text", ""))))

            await _stop_session_watch(chat_id)
            if bool(payload.get("running", False)):
                session_watch_tasks[chat_id] = asyncio.create_task(_watch_session_live(chat_id, sid, history_msg.chat_id, history_msg.message_id))
            return

        if data.startswith("shis:"):
            sid = data.split(":", 1)[1]
            history_text = runner.session_history_text(chat_id, sid)
            keyboard = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("刷新历史", callback_data=f"shis:{sid}")],
                    [InlineKeyboardButton("返回详情", callback_data=f"sopen:{sid}")],
                    [InlineKeyboardButton("返回列表", callback_data="smenu:0")],
                ]
            )
            await query.edit_message_text(history_text, reply_markup=keyboard)
            return

        if data.startswith("sdel:"):
            sid = data.split(":", 1)[1]
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
        text = runner.session_detail_text(chat_id, session_id)
        if prefix:
            text = f"{prefix}\n\n{text}"
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("接管会话", callback_data=f"suse:{session_id}")],
                [InlineKeyboardButton("查看历史", callback_data=f"shis:{session_id}")],
                [InlineKeyboardButton("刷新详情", callback_data=f"sopen:{session_id}")],
                [InlineKeyboardButton("删除会话", callback_data=f"sdel:{session_id}")],
                [InlineKeyboardButton("返回列表", callback_data="smenu:0")],
            ]
        )
        await query.edit_message_text(text, reply_markup=keyboard)

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

    builder = ApplicationBuilder().token(settings.telegram_bot_token)
    if settings.telegram_proxy_url:
        builder = builder.proxy(settings.telegram_proxy_url).get_updates_proxy(settings.telegram_proxy_url)

    application = builder.post_init(on_startup).build()

    application.add_handler(CommandHandler("whoami", whoami_command))
    application.add_handler(CommandHandler("llm", restricted(settings, llm_command)))
    application.add_handler(CommandHandler("session_current", restricted(settings, session_current_command)))
    application.add_handler(CommandHandler("sessions", restricted(settings, sessions_command)))
    application.add_handler(CommandHandler("session_new", restricted(settings, session_new_command)))
    application.add_handler(CommandHandler("session_use", restricted(settings, session_use_command)))
    application.add_handler(CommandHandler("model", restricted(settings, model_command)))
    application.add_handler(CommandHandler("start", restricted(settings, start_command)))
    application.add_handler(CommandHandler("help", restricted(settings, help_command)))
    application.add_handler(CommandHandler("status", restricted(settings, status_command)))
    application.add_handler(CallbackQueryHandler(model_select_callback, pattern=r"^model_sel:"))
    application.add_handler(CallbackQueryHandler(session_callback, pattern=r"^(smenu:|sopen:|suse:|shis:|sdel:)"))
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


def _build_model_keyboard(models: list[str], current: str) -> list[list[InlineKeyboardButton]]:
    """构建模型选择内联键盘（2列布局，当前模型标 ✓）"""
    keyboard: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for model in models:
        label = f"✓ {model}" if model == current else model
        row.append(InlineKeyboardButton(label, callback_data=f"model_sel:{model}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return keyboard


def _trim_telegram_text(text: str, limit: int = 3500) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _render_session_menu(items: list[dict], page: int, page_size: int = 6) -> tuple[str, list[list[InlineKeyboardButton]]]:
    total = len(items)
    if total == 0:
        return "未发现可管理会话", [[InlineKeyboardButton("刷新", callback_data="smenu:0")]]

    max_page = max((total - 1) // page_size, 0)
    page = max(0, min(page, max_page))
    start = page * page_size
    current_items = items[start : start + page_size]

    lines = [f"会话管理 第 {page + 1}/{max_page + 1} 页"]
    keyboard: list[list[InlineKeyboardButton]] = []

    for item in current_items:
        sid = str(item.get("id", ""))
        short_sid = sid[:8]
        model = str(item.get("model") or "unknown")
        running = "🟢" if item.get("running") else "⚪"
        active = "⭐" if item.get("active") else ""
        lines.append(f"{running}{active} {short_sid} | {model}")
        keyboard.append([InlineKeyboardButton(f"打开 {short_sid}", callback_data=f"sopen:{sid}")])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton("上一页", callback_data=f"smenu:{page - 1}"))
    nav.append(InlineKeyboardButton("刷新", callback_data=f"smenu:{page}"))
    if page < max_page:
        nav.append(InlineKeyboardButton("下一页", callback_data=f"smenu:{page + 1}"))
    keyboard.append(nav)

    return "\n".join(lines), keyboard
