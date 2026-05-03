from __future__ import annotations

from topilot.telegram_bot import _build_model_keyboard, _chunk_text, _render_session_menu, _trim_telegram_text


def test_model_keyboard_marks_current_model_and_uses_two_columns() -> None:
    keyboard = _build_model_keyboard(["gpt-5-mini", "gpt-5", "claude"], "gpt-5")

    assert len(keyboard) == 2
    assert len(keyboard[0]) == 2
    assert keyboard[0][1].text == "✓ gpt-5"
    assert keyboard[1][0].text == "claude"


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
            {"id": "abcdef123456", "model": "gpt-5-mini", "running": True, "active": True},
            {"id": "fedcba654321", "model": "gpt-5", "running": False, "active": False},
        ],
        page=0,
        page_size=6,
    )

    assert "🟢⭐ abcdef12 | gpt-5-mini" in text
    assert "⚪ fedcba65 | gpt-5" in text
    assert keyboard[0][0].callback_data == "sopen:abcdef123456"
