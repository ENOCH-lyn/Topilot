from __future__ import annotations

import asyncio

from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler

from topilot.telegram_bot import (
    _build_model_keyboard,
    _callback_page,
    _callback_payload,
    _chunk_text,
    _is_allowed,
    _normalize_model_list,
    _render_model_menu,
    _render_session_delete_confirm,
    _render_session_detail,
    _render_session_history,
    _render_session_menu,
    _trim_telegram_text,
    restricted,
)


class FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, chat_id: int | None) -> None:
        self.effective_chat = FakeChat(chat_id) if chat_id is not None else None
        self.effective_message = FakeMessage()


def test_model_keyboard_marks_current_model_and_uses_two_columns() -> None:
    keyboard = _build_model_keyboard(["gpt-5-mini", "gpt-5", "claude"], "gpt-5")

    assert len(keyboard) == 2
    assert len(keyboard[0]) == 2
    assert keyboard[0][1].text == "✓ gpt-5"
    assert keyboard[1][0].text == "claude"


def test_model_menu_deduplicates_models_and_keeps_callback_values() -> None:
    text, keyboard = _render_model_menu(["gpt-5", " ", "gpt-5-mini", "gpt-5"], "gpt-5-mini")

    assert text == "当前模型: gpt-5-mini\n请选择模型:"
    assert _normalize_model_list(["gpt-5", "", "gpt-5-mini", "gpt-5"]) == ["gpt-5", "gpt-5-mini"]
    assert len(keyboard) == 1
    assert keyboard[0][0].text == "gpt-5"
    assert keyboard[0][0].callback_data == "model_sel:gpt-5"
    assert keyboard[0][1].text == "✓ gpt-5-mini"
    assert keyboard[0][1].callback_data == "model_sel:gpt-5-mini"


def test_chunk_and_trim_helpers_keep_telegram_safe_lengths() -> None:
    text = "a" * 7200

    chunks = _chunk_text(text, limit=3500)
    trimmed = _trim_telegram_text(text, limit=3500)

    assert [len(chunk) for chunk in chunks] == [3500, 3500, 200]
    assert len(trimmed) == 3503
    assert trimmed.endswith("...")


def test_render_session_menu_shows_active_and_running_marks() -> None:
    text, keyboard = _render_session_menu(
        [
            {
                "id": "abcdef123456",
                "title": "mobile checkout bug",
                "model": "gpt-5-mini",
                "source": "local",
                "running": True,
                "active": True,
            },
            {
                "id": "fedcba654321",
                "title": "docs",
                "model": "gpt-5",
                "source": "saved",
                "running": False,
                "active": False,
            },
        ],
        page=0,
        page_size=6,
    )

    assert "🟢⭐ abcdef12 | mobile checkout bu... | gpt-5-mini | local" in text
    assert "⚪ fedcba65 | docs | gpt-5 | saved" in text
    assert keyboard[0][0].callback_data == "sopen:abcdef123456"
    assert keyboard[0][0].text == "打开 abcdef12 mobile checkout bu..."


def test_render_session_menu_paginates_and_clamps_page_bounds() -> None:
    items = [
        {
            "id": f"session-{index:02d}",
            "title": f"title-{index}",
            "model": "gpt-5-mini",
            "source": "saved",
            "running": False,
            "active": False,
        }
        for index in range(8)
    ]

    first_text, first_keyboard = _render_session_menu(items, page=-2, page_size=3)
    last_text, last_keyboard = _render_session_menu(items, page=99, page_size=3)

    assert first_text.startswith("会话管理 第 1/3 页")
    assert first_keyboard[-1][0].text == "刷新"
    assert first_keyboard[-1][0].callback_data == "smenu:0"
    assert first_keyboard[-1][1].text == "下一页"
    assert first_keyboard[-1][1].callback_data == "smenu:1"
    assert last_text.startswith("会话管理 第 3/3 页")
    assert last_keyboard[-1][0].text == "上一页"
    assert last_keyboard[-1][0].callback_data == "smenu:1"
    assert last_keyboard[-1][1].text == "刷新"
    assert last_keyboard[-1][1].callback_data == "smenu:2"


def test_render_session_detail_history_and_delete_confirm_buttons() -> None:
    detail_text, detail_keyboard = _render_session_detail(
        "会话: session-123\n状态: 空闲",
        "session-123",
        prefix="已刷新",
    )
    history_text, history_keyboard = _render_session_history("最近历史:\n- hello", "session-123")
    delete_text, delete_keyboard = _render_session_delete_confirm("会话: session-123\n状态: 空闲", "session-123")

    assert detail_text.startswith("已刷新\n\n会话: session-123")
    assert [row[0].callback_data for row in detail_keyboard] == [
        "suse:session-123",
        "shis:session-123",
        "sopen:session-123",
        "sdel:session-123",
        "smenu:0",
    ]
    assert history_text == "最近历史:\n- hello"
    assert [row[0].callback_data for row in history_keyboard] == [
        "shis:session-123",
        "sopen:session-123",
        "smenu:0",
    ]
    assert delete_text.startswith("确认删除该会话？\n\n会话: session-123")
    assert [row[0].callback_data for row in delete_keyboard] == [
        "sdelok:session-123",
        "sopen:session-123",
        "smenu:0",
    ]


def test_callback_payload_and_page_parsing_are_safe() -> None:
    assert _callback_payload("sopen:session-123", "sopen:") == "session-123"
    assert _callback_payload("sopen:  session-123  ", "sopen:") == "session-123"
    assert _callback_payload("shis:session-123", "sopen:") == ""
    assert _callback_page("smenu:2") == 2
    assert _callback_page("smenu:-1") == 0
    assert _callback_page("smenu:not-a-number") == 0
    assert _callback_page("sopen:1") == 0


def test_is_allowed_respects_empty_allowlist_and_explicit_chat_ids(make_settings) -> None:
    open_settings = make_settings(allowed_chat_ids=set())
    locked_settings = make_settings(allowed_chat_ids={100})

    assert _is_allowed(open_settings, 999) is True
    assert _is_allowed(locked_settings, 100) is True
    assert _is_allowed(locked_settings, 999) is False
    assert _is_allowed(locked_settings, None) is False


def test_restricted_handler_allows_authorized_chat(make_settings) -> None:
    settings = make_settings(allowed_chat_ids={100})
    called: list[int] = []

    async def handler(update, context) -> None:
        called.append(update.effective_chat.id)

    update = FakeUpdate(100)

    asyncio.run(restricted(settings, handler)(update, object()))

    assert called == [100]
    assert update.effective_message.replies == []


def test_restricted_handler_rejects_unauthorized_chat(make_settings) -> None:
    settings = make_settings(allowed_chat_ids={100})
    called: list[int] = []

    async def handler(update, context) -> None:
        called.append(update.effective_chat.id)

    update = FakeUpdate(999)

    asyncio.run(restricted(settings, handler)(update, object()))

    assert called == []
    assert update.effective_message.replies == [
        "当前用户未授权，请使用 /whoami 获取 chat id，并写入配置项 telegram.allowed_chat_ids"
    ]


def test_build_application_registers_required_commands_callbacks_and_text_handler(make_settings) -> None:
    from topilot.telegram_bot import build_application

    app = build_application(make_settings())
    handlers = app.handlers[0]

    command_handlers = [handler for handler in handlers if isinstance(handler, CommandHandler)]
    commands = {
        command
        for handler in command_handlers
        for command in handler.commands
    }

    assert commands == {
        "whoami",
        "llm",
        "session_current",
        "sessions",
        "session_new",
        "session_use",
        "model",
        "start",
        "help",
        "status",
    }

    callback_patterns = [
        handler.pattern.pattern
        for handler in handlers
        if isinstance(handler, CallbackQueryHandler)
    ]
    assert callback_patterns == [
        "^model_sel:",
        r"^(smenu:|sopen:|suse:|shis:|sdel:|sdelok:)",
    ]

    message_handlers = [handler for handler in handlers if isinstance(handler, MessageHandler)]
    assert len(message_handlers) == 1

    callbacks_by_command = {
        next(iter(handler.commands)): handler.callback.__qualname__
        for handler in command_handlers
    }
    assert callbacks_by_command["whoami"].endswith("whoami_command")
    for command in commands - {"whoami"}:
        assert callbacks_by_command[command].endswith("restricted.<locals>.wrapped")
