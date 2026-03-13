from __future__ import annotations

from collections.abc import Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from copilot_in_telegram.config import Settings
from copilot_in_telegram.task_runner import TaskRunner

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def _is_allowed(settings: Settings, chat_id: int | None) -> bool:
    if chat_id is None:
        return False
    if not settings.allowed_chat_ids:
        return True
    return chat_id in settings.allowed_chat_ids


def restricted(settings: Settings, handler: Handler) -> Handler:
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not _is_allowed(settings, chat_id):
            if update.effective_message:
                await update.effective_message.reply_text("当前 chat 未授权。先发 /whoami 获取 chat id，再把它加入 TELEGRAM_ALLOWED_CHAT_IDS。")
            return
        await handler(update, context)

    return wrapped


def build_application(settings: Settings) -> Application:
    application: Application | None = None

    async def send_message(chat_id: int, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        if application is None:
            return
        reply_markup = None
        if buttons:
            keyboard = [[InlineKeyboardButton(label, callback_data=data)] for label, data in buttons]
            reply_markup = InlineKeyboardMarkup(keyboard)
        for chunk in _chunk_text(text):
            await application.bot.send_message(chat_id=chat_id, text=chunk, reply_markup=reply_markup)
            reply_markup = None

    runner = TaskRunner(settings, send_message)

    async def on_startup(app: Application) -> None:
        await runner.start()
        app.bot_data["runner"] = runner

    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "可用命令:\n"
            "/whoami\n"
            "/llm\n"
            "/session_current\n"
            "/sessions\n"
            "/session_new [title]\n"
            "/session_use <session_id前缀>\n"
            "/run <指令>\n"
            "/status\n"
            "/history\n"
            "/reset\n"
            "/interrupt [task_id]\n"
            "/approve <task_id>\n"
            "/deny <task_id>\n"
            "也可直接发送文本"
        )

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "建议用法:\n"
            "/whoami 查看当前 chat id\n"
            "/llm 查看 Copilot 后端状态\n"
            "/session_current 查看当前会话\n"
            "/sessions 列出会话历史\n"
            "/session_new 新建会话\n"
            "/session_use <id前缀> 切换会话\n"
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
        if not update.effective_message:
            return
        await update.effective_message.reply_text(f"后端状态: {runner.llm_status_text()}")

    async def session_current_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        await update.effective_message.reply_text(runner.session_current_text(update.effective_chat.id))

    async def sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        await update.effective_message.reply_text(runner.session_list_text(update.effective_chat.id))

    async def session_new_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        title = " ".join(context.args).strip() if context.args else None
        await update.effective_message.reply_text(runner.session_new_text(update.effective_chat.id, title))

    async def session_use_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        if not context.args:
            await update.effective_message.reply_text("请提供会话 ID 前缀。")
            return
        await update.effective_message.reply_text(runner.session_use_text(update.effective_chat.id, context.args[0]))

    async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        instruction = " ".join(context.args).strip()
        if not instruction:
            await update.effective_message.reply_text("请提供要执行的指令。")
            return
        await runner.submit(update.effective_chat.id, instruction)

    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        await update.effective_message.reply_text(runner.status_text(update.effective_chat.id))

    async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        await update.effective_message.reply_text(runner.history_text(update.effective_chat.id))

    async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        await update.effective_message.reply_text(runner.reset_text(update.effective_chat.id))

    async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        task_id = context.args[0].strip() if context.args else ""
        if not task_id:
            await update.effective_message.reply_text("请提供 task_id。")
            return
        try:
            text = await runner.approve(update.effective_chat.id, task_id)
        except ValueError as exc:
            text = str(exc)
        await update.effective_message.reply_text(text)

    async def deny_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        task_id = context.args[0].strip() if context.args else ""
        if not task_id:
            await update.effective_message.reply_text("请提供 task_id。")
            return
        try:
            text = await runner.deny(update.effective_chat.id, task_id)
        except ValueError as exc:
            text = str(exc)
        await update.effective_message.reply_text(text)

    async def interrupt_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat:
            return
        task_id = context.args[0].strip() if context.args else None
        try:
            text = await runner.interrupt(update.effective_chat.id, task_id)
        except ValueError as exc:
            text = str(exc)
        await update.effective_message.reply_text(text)

    async def approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.callback_query or not update.effective_chat:
            return
        query = update.callback_query
        await query.answer()
        payload = query.data or ""
        action, _, task_id = payload.partition(":")
        if not task_id:
            await query.edit_message_text("按钮数据无效。")
            return

        try:
            if action == "approve":
                result = await runner.approve(update.effective_chat.id, task_id)
            elif action == "deny":
                result = await runner.deny(update.effective_chat.id, task_id)
            elif action == "interrupt":
                result = await runner.interrupt(update.effective_chat.id, task_id)
            else:
                result = "未知动作。"
        except ValueError as exc:
            result = str(exc)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(result)

    async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat or not update.effective_message.text:
            return
        await runner.submit(update.effective_chat.id, update.effective_message.text)

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
    application.add_handler(CommandHandler("start", restricted(settings, start_command)))
    application.add_handler(CommandHandler("help", restricted(settings, help_command)))
    application.add_handler(CommandHandler("run", restricted(settings, run_command)))
    application.add_handler(CommandHandler("status", restricted(settings, status_command)))
    application.add_handler(CommandHandler("history", restricted(settings, history_command)))
    application.add_handler(CommandHandler("reset", restricted(settings, reset_command)))
    application.add_handler(CommandHandler("interrupt", restricted(settings, interrupt_command)))
    application.add_handler(CommandHandler("approve", restricted(settings, approve_command)))
    application.add_handler(CommandHandler("deny", restricted(settings, deny_command)))
    application.add_handler(CallbackQueryHandler(restricted(settings, approval_callback), pattern=r"^(approve|deny|interrupt):"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, restricted(settings, text_message)))

    return application


def _chunk_text(text: str, limit: int = 3500) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]
    return chunks
