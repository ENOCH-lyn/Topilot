from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from topilot.feishu_bot import (
    _FeishuActionContext,
    _FeishuLiveProgress,
    _CARD_SESSION_DETAIL,
    _CARD_SESSION_HISTORY,
    _CARD_SESSIONS_PAGE,
    _CARD_SESSION_USE,
    _MENU_MODEL,
    _CARD_MODEL_SET,
    _CARD_STATUS,
    _check_feishu_response,
    _feishu_is_allowed,
    _parse_text_content,
    FeishuBotRunner,
)


def test_parse_text_content_supports_json_and_plain_text() -> None:
    assert _parse_text_content(json.dumps({"text": "hello"}, ensure_ascii=False)) == "hello"
    assert _parse_text_content("plain text") == "plain text"
    assert (
        _parse_text_content(
            json.dumps(
                {
                    "zh_cn": {
                        "title": "指令",
                        "content": [
                            [{"tag": "text", "text": "/status"}],
                            [{"tag": "text", "text": "查看当前状态"}],
                        ],
                    }
                },
                ensure_ascii=False,
            )
        )
        == "指令\n/status\n查看当前状态"
    )
    assert _parse_text_content(None) == ""


def test_feishu_is_allowed_respects_chat_and_open_id_allowlists(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_allowed_chat_ids={"oc_chat_1"},
        feishu_allowed_open_ids={"ou_user_1"},
    )

    assert _feishu_is_allowed(settings, "oc_chat_1", "ou_user_1") is True
    assert _feishu_is_allowed(settings, "oc_chat_2", "ou_user_1") is False
    assert _feishu_is_allowed(settings, "oc_chat_1", "ou_user_2") is False


def test_feishu_runner_forwards_text_message_into_task_runner(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    captured: list[tuple[str, str]] = []

    class FakeTaskRunner:
        async def submit(self, chat_id: str, instruction: str) -> None:
            captured.append((chat_id, instruction))

    runner._runner = FakeTaskRunner()
    event = SimpleNamespace(
        sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_test")),
        message=SimpleNamespace(
            message_type="text",
            chat_id="oc_chat_1",
            message_id="om_xxx",
            content=json.dumps({"text": "你好"}, ensure_ascii=False),
        ),
    )
    payload = SimpleNamespace(event=event)

    asyncio.run(runner._handle_message_event(payload))

    assert captured == [("feishu:oc_chat_1", "你好")]


def test_feishu_runner_forwards_post_message_into_task_runner(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    captured: list[tuple[str, str]] = []

    class FakeTaskRunner:
        async def submit(self, chat_id: str, instruction: str) -> None:
            captured.append((chat_id, instruction))

    runner._runner = FakeTaskRunner()
    event = SimpleNamespace(
        sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_test")),
        message=SimpleNamespace(
            message_type="post",
            chat_id="oc_chat_1",
            message_id="om_post",
            content=json.dumps(
                {
                    "zh_cn": {
                        "content": [[{"tag": "text", "text": "你好，继续测试"}]],
                    }
                },
                ensure_ascii=False,
            ),
        ),
    )

    asyncio.run(runner._handle_message_event(SimpleNamespace(event=event)))

    assert captured == [("feishu:oc_chat_1", "你好，继续测试")]


def test_feishu_runner_rejects_unauthorized_message(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
        feishu_allowed_chat_ids={"oc_allowed"},
    )
    runner = FeishuBotRunner(settings)
    denied: list[str] = []

    class FakeTaskRunner:
        async def submit(self, chat_id: str, instruction: str) -> None:
            raise AssertionError("unauthorized message should not reach task runner")

    async def fake_reply(message_id: str) -> None:
        denied.append(message_id)

    runner._runner = FakeTaskRunner()
    runner._reply_permission_denied = fake_reply
    event = SimpleNamespace(
        sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_test")),
        message=SimpleNamespace(
            message_type="text",
            chat_id="oc_denied",
            message_id="om_denied",
            content=json.dumps({"text": "blocked"}, ensure_ascii=False),
        ),
    )

    asyncio.run(runner._handle_message_event(SimpleNamespace(event=event)))

    assert denied == ["om_denied"]


def test_feishu_text_command_routes_to_action(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    captured: list[str] = []

    async def fake_dispatch(context, action: str, **kwargs):
        captured.append(action)
        return None

    runner._dispatch_action = fake_dispatch

    handled = asyncio.run(runner._try_handle_text_command(runner._chat_target("oc_chat_1"), "oc_chat_1", "ou_test", "/model"))

    assert handled is True
    assert captured == [_MENU_MODEL]


def test_feishu_dispatch_model_switch_updates_runner(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    switched: list[str] = []

    class FakeTaskRunner:
        def current_model(self, chat_key: str) -> str:
            return switched[-1] if switched else "gpt-5-mini"

        def list_models(self) -> list[str]:
            return ["gpt-5-mini", "gpt-5.5"]

        def set_model(self, chat_key: str, model: str) -> None:
            switched.append(model)

    runner._runner = FakeTaskRunner()
    context = _FeishuActionContext(target=runner._chat_target("oc_chat_1"), open_id="ou_test", chat_id="oc_chat_1")

    card_json = asyncio.run(runner._dispatch_action(context, _CARD_MODEL_SET, model="gpt-5.5", return_card=True))

    assert switched == ["gpt-5.5"]
    assert card_json is not None
    assert "已切换模型" in card_json


def test_feishu_menu_event_dispatches_action(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    captured: list[tuple[str, str, str]] = []

    async def fake_dispatch(context, action: str, **kwargs):
        captured.append((context.target.session_key, context.open_id, action))
        return None

    runner._dispatch_action = fake_dispatch
    payload = SimpleNamespace(
        event=SimpleNamespace(
            operator=SimpleNamespace(operator_id=SimpleNamespace(open_id="ou_menu")),
            event_key=_MENU_MODEL,
        )
    )

    asyncio.run(runner._handle_menu_event(payload))

    assert captured == [("feishu-open:ou_menu", "ou_menu", _MENU_MODEL)]


def test_feishu_menu_event_sync_returns_ack(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    scheduled: list[object] = []

    def fake_schedule(coro) -> None:
        scheduled.append(coro)
        coro.close()

    runner._schedule = fake_schedule
    payload = SimpleNamespace(event=SimpleNamespace(operator=SimpleNamespace(operator_id=SimpleNamespace(open_id="ou_menu")), event_key=_MENU_MODEL))

    result = runner._handle_menu_event_sync(payload)

    assert result == {}
    assert len(scheduled) == 1


def test_feishu_card_action_returns_updated_card(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    card_json = json.dumps({"header": {"title": "ok"}}, ensure_ascii=False)

    class FakeCallbackCard:
        def __init__(self) -> None:
            self.type = None
            self.data = None

    class FakeCallbackToast:
        def __init__(self) -> None:
            self.type = None
            self.content = None

    class FakeCallbackResponse:
        def __init__(self) -> None:
            self.toast = None
            self.card = None

    def fake_dispatch_sync(context, action: str, *, model: str | None = None, session_id: str | None = None, page: int = 0):
        assert context.target.session_key == "feishu:oc_card"
        assert context.message_id == "om_card"
        assert action == _CARD_STATUS
        assert page == 0
        assert session_id == ""
        return card_json

    runner._dispatch_action_sync = fake_dispatch_sync
    runner._callback_card = FakeCallbackCard
    runner._callback_toast = FakeCallbackToast
    runner._callback_response = FakeCallbackResponse
    payload = SimpleNamespace(
        event=SimpleNamespace(
            operator=SimpleNamespace(open_id="ou_card"),
            context=SimpleNamespace(open_chat_id="oc_card", open_message_id="om_card"),
            action=SimpleNamespace(value={"action": _CARD_STATUS}),
        )
    )

    response = asyncio.run(runner._handle_card_action(payload))

    assert response.toast.type == "info"
    assert response.toast.content == "已更新"
    assert response.card.type == "raw"
    assert response.card.data == {"header": {"title": "ok"}}


def test_feishu_card_action_sync_returns_response_without_event_loop_wait(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    captured: list[tuple[str, str | None]] = []

    class FakeCallbackCard:
        def __init__(self) -> None:
            self.type = None
            self.data = None

    class FakeCallbackToast:
        def __init__(self) -> None:
            self.type = None
            self.content = None

    class FakeCallbackResponse:
        def __init__(self) -> None:
            self.toast = None
            self.card = None

    def fake_dispatch_sync(context, action: str, *, model: str | None = None, session_id: str | None = None, page: int = 0):
        captured.append((action, model))
        assert session_id == ""
        return json.dumps({"sync": True}, ensure_ascii=False)

    runner._dispatch_action_sync = fake_dispatch_sync
    runner._callback_card = FakeCallbackCard
    runner._callback_toast = FakeCallbackToast
    runner._callback_response = FakeCallbackResponse
    payload = SimpleNamespace(
        event=SimpleNamespace(
            operator=SimpleNamespace(open_id="ou_card"),
            context=SimpleNamespace(open_chat_id="oc_card", open_message_id="om_card"),
            action=SimpleNamespace(value={"action": _CARD_MODEL_SET, "model": "gpt-5.5"}),
        )
    )

    response = runner._handle_card_action_sync(payload)

    assert captured == [(_CARD_MODEL_SET, "gpt-5.5")]
    assert response.toast.content == "已更新"
    assert response.card.data == {"sync": True}


def test_feishu_card_action_sync_parses_sessions_page_value(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    captured: list[tuple[str, int]] = []

    class FakeCallbackCard:
        def __init__(self) -> None:
            self.type = None
            self.data = None

    class FakeCallbackToast:
        def __init__(self) -> None:
            self.type = None
            self.content = None

    class FakeCallbackResponse:
        def __init__(self) -> None:
            self.toast = None
            self.card = None

    def fake_dispatch_sync(context, action: str, *, model: str | None = None, session_id: str | None = None, page: int = 0):
        captured.append((action, page))
        assert session_id == ""
        return json.dumps({"page": page}, ensure_ascii=False)

    runner._dispatch_action_sync = fake_dispatch_sync
    runner._callback_card = FakeCallbackCard
    runner._callback_toast = FakeCallbackToast
    runner._callback_response = FakeCallbackResponse
    payload = SimpleNamespace(
        event=SimpleNamespace(
            operator=SimpleNamespace(open_id="ou_card"),
            context=SimpleNamespace(open_chat_id="oc_card", open_message_id="om_card"),
            action=SimpleNamespace(value={"action": _CARD_SESSIONS_PAGE, "page": "2"}),
        )
    )

    response = runner._handle_card_action_sync(payload)

    assert captured == [(_CARD_SESSIONS_PAGE, 2)]
    assert response.card.data == {"page": 2}


def test_feishu_card_action_sync_parses_session_use_value(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    captured: list[tuple[str, str | None, int]] = []

    class FakeCallbackCard:
        def __init__(self) -> None:
            self.type = None
            self.data = None

    class FakeCallbackToast:
        def __init__(self) -> None:
            self.type = None
            self.content = None

    class FakeCallbackResponse:
        def __init__(self) -> None:
            self.toast = None
            self.card = None

    def fake_dispatch_sync(context, action: str, *, model: str | None = None, session_id: str | None = None, page: int = 0):
        captured.append((action, session_id, page))
        return json.dumps({"session_id": session_id, "page": page}, ensure_ascii=False)

    runner._dispatch_action_sync = fake_dispatch_sync
    runner._callback_card = FakeCallbackCard
    runner._callback_toast = FakeCallbackToast
    runner._callback_response = FakeCallbackResponse
    payload = SimpleNamespace(
        event=SimpleNamespace(
            operator=SimpleNamespace(open_id="ou_card"),
            context=SimpleNamespace(open_chat_id="oc_card", open_message_id="om_card"),
            action=SimpleNamespace(value={"action": _CARD_SESSION_USE, "session_id": "session-123", "page": "1"}),
        )
    )

    response = runner._handle_card_action_sync(payload)

    assert captured == [(_CARD_SESSION_USE, "session-123", 1)]
    assert response.card.data == {"session_id": "session-123", "page": 1}


def test_feishu_card_action_sync_parses_session_detail_value(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    captured: list[tuple[str, str | None, int]] = []

    class FakeCallbackCard:
        def __init__(self) -> None:
            self.type = None
            self.data = None

    class FakeCallbackToast:
        def __init__(self) -> None:
            self.type = None
            self.content = None

    class FakeCallbackResponse:
        def __init__(self) -> None:
            self.toast = None
            self.card = None

    def fake_dispatch_sync(context, action: str, *, model: str | None = None, session_id: str | None = None, page: int = 0):
        captured.append((action, session_id, page))
        return json.dumps({"detail": session_id, "page": page}, ensure_ascii=False)

    runner._dispatch_action_sync = fake_dispatch_sync
    runner._callback_card = FakeCallbackCard
    runner._callback_toast = FakeCallbackToast
    runner._callback_response = FakeCallbackResponse
    payload = SimpleNamespace(
        event=SimpleNamespace(
            operator=SimpleNamespace(open_id="ou_card"),
            context=SimpleNamespace(open_chat_id="oc_card", open_message_id="om_card"),
            action=SimpleNamespace(value={"action": _CARD_SESSION_DETAIL, "session_id": "session-456", "page": "3"}),
        )
    )

    response = runner._handle_card_action_sync(payload)

    assert captured == [(_CARD_SESSION_DETAIL, "session-456", 3)]
    assert response.card.data == {"detail": "session-456", "page": 3}


def test_feishu_send_result_message_uses_plain_text(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    sent: list[tuple[str, str]] = []

    async def fake_send_text(target, text: str) -> None:
        sent.append((target.session_key, text))

    runner._send_text_message = fake_send_text

    asyncio.run(runner._send_result_message(runner._chat_target("oc_chat_1"), "最终回复"))

    assert sent == [("feishu:oc_chat_1", "最终回复")]


def test_feishu_sessions_card_uses_paginated_merged_items(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)

    class FakeTaskRunner:
        def session_menu_items(self, chat_key: str, limit: int = 20) -> list[dict]:
            assert limit == 120
            return [
                {
                    "id": f"session-{index:02d}",
                    "title": f"title-{index}",
                    "model": "gpt-5-mini",
                    "source": "local",
                    "running": index % 2 == 0,
                    "active": index == 11,
                }
                for index in range(13)
            ]

    runner._runner = FakeTaskRunner()
    context = _FeishuActionContext(target=runner._chat_target("oc_chat_1"), open_id="ou_test", chat_id="oc_chat_1")

    card_json = runner._build_sessions_card(context, page=1)
    payload = json.loads(card_json)
    body = payload["elements"][0]["text"]["content"]
    action_rows = [item["actions"] for item in payload["elements"] if item["tag"] == "action"]

    assert "第 2/2 页，共 13 个会话" in body
    assert "title-10" in body
    assert "title-12" in body
    assert any(action["value"]["action"] == _CARD_SESSIONS_PAGE and action["value"]["page"] == "0" for action in action_rows[0])
    assert any(action["value"]["action"] == _CARD_SESSION_USE and action["value"]["session_id"] == "session-10" for row in action_rows[1:] for action in row)
    assert any(action["value"]["action"] == _CARD_SESSION_DETAIL and action["value"]["session_id"] == "session-10" for row in action_rows[1:] for action in row)


def test_feishu_dispatch_session_use_returns_history_card(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)

    class FakeTaskRunner:
        def session_use_text(self, chat_key: str, session_prefix: str) -> str:
            assert chat_key == "feishu:oc_chat_1"
            assert session_prefix == "session-123"
            return "已切换到会话: session-123"

        def session_history_text(self, chat_key: str, session_id: str) -> str:
            assert chat_key == "feishu:oc_chat_1"
            assert session_id == "session-123"
            return "最近历史:\n- hello"

    runner._runner = FakeTaskRunner()
    context = _FeishuActionContext(target=runner._chat_target("oc_chat_1"), open_id="ou_test", chat_id="oc_chat_1")

    card_json = asyncio.run(runner._dispatch_action(context, _CARD_SESSION_USE, session_id="session-123", page=0, return_card=True))

    assert card_json is not None
    assert "已切换到会话: session-123" in card_json
    assert "最近历史" in card_json


def test_feishu_dispatch_session_use_starts_live_watch_for_running_session(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    scheduled: list[asyncio.Task] = []
    stopped_keys: list[str] = []

    class FakeTaskRunner:
        def session_use_text(self, chat_key: str, session_prefix: str) -> str:
            return "已切换到会话: session-123"

        def session_history_text(self, chat_key: str, session_id: str) -> str:
            return "最近历史:\n- line"

        def session_live_payload(self, chat_key: str, session_id: str) -> dict:
            return {"exists": True, "running": True, "text": "x", "signature": "sig"}

    async def fake_stop_all(session_key: str) -> None:
        stopped_keys.append(session_key)

    async def fake_watch(context, session_id: str, page: int = 0) -> None:
        return None

    def fake_create_task(coro):
        task = SimpleNamespace(cancel=lambda: None, done=lambda: False)
        scheduled.append(task)
        coro.close()
        return task

    runner._runner = FakeTaskRunner()
    runner._stop_all_session_watches = fake_stop_all
    runner._watch_session_live = fake_watch
    context = _FeishuActionContext(target=runner._chat_target("oc_chat_1"), open_id="ou_test", chat_id="oc_chat_1", message_id="om_card")

    original_create_task = asyncio.create_task
    asyncio.create_task = fake_create_task
    try:
        card_json = asyncio.run(runner._dispatch_action(context, _CARD_SESSION_USE, session_id="session-123", page=1, return_card=True))
    finally:
        asyncio.create_task = original_create_task

    assert card_json is not None
    assert "最近历史" in card_json
    assert stopped_keys == ["feishu:oc_chat_1"]
    assert "feishu:oc_chat_1:session-123" in runner._session_watch_tasks


def test_feishu_dispatch_session_detail_renders_preview_card(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)

    class FakeTaskRunner:
        def session_detail_text(self, chat_key: str, session_id: str) -> str:
            assert chat_key == "feishu:oc_chat_1"
            assert session_id == "session-123"
            return "会话: session-123\n状态: 运行中"

    runner._runner = FakeTaskRunner()
    context = _FeishuActionContext(target=runner._chat_target("oc_chat_1"), open_id="ou_test", chat_id="oc_chat_1")

    card_json = asyncio.run(runner._dispatch_action(context, _CARD_SESSION_DETAIL, session_id="session-123", page=2, return_card=True))

    assert card_json is not None
    assert "会话: session-123" in card_json
    assert "查看历史" in card_json


def test_feishu_dispatch_session_history_starts_live_watch_for_running_session(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    scheduled: list[asyncio.Task] = []
    stopped: list[str] = []

    class FakeTaskRunner:
        def session_history_text(self, chat_key: str, session_id: str) -> str:
            return "最近历史:\n- line"

        def session_live_payload(self, chat_key: str, session_id: str) -> dict:
            return {"exists": True, "running": True, "text": "x", "signature": "sig"}

    async def fake_stop(watch_key: str) -> None:
        stopped.append(watch_key)

    async def fake_watch(context, session_id: str, page: int = 0) -> None:
        return None

    def fake_create_task(coro):
        task = SimpleNamespace(cancel=lambda: None, done=lambda: False)
        scheduled.append(task)
        coro.close()
        return task

    runner._runner = FakeTaskRunner()
    runner._stop_session_watch = fake_stop
    runner._watch_session_live = fake_watch
    context = _FeishuActionContext(target=runner._chat_target("oc_chat_1"), open_id="ou_test", chat_id="oc_chat_1", message_id="om_card")

    original_create_task = asyncio.create_task
    asyncio.create_task = fake_create_task
    try:
        card_json = asyncio.run(runner._dispatch_action(context, _CARD_SESSION_HISTORY, session_id="session-123", page=1, return_card=True))
    finally:
        asyncio.create_task = original_create_task

    assert card_json is not None
    assert "最近历史" in card_json
    assert stopped == ["feishu:oc_chat_1:session-123"]
    assert "feishu:oc_chat_1:session-123" in runner._session_watch_tasks


def test_feishu_card_action_sync_schedules_follow_up_for_live_session_cards(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    scheduled: list[object] = []

    class FakeCallbackCard:
        def __init__(self) -> None:
            self.type = None
            self.data = None

    class FakeCallbackToast:
        def __init__(self) -> None:
            self.type = None
            self.content = None

    class FakeCallbackResponse:
        def __init__(self) -> None:
            self.toast = None
            self.card = None

    def fake_dispatch_sync(context, action: str, *, model: str | None = None, session_id: str | None = None, page: int = 0):
        return json.dumps({"action": action, "session_id": session_id, "page": page}, ensure_ascii=False)

    def fake_schedule(coro) -> None:
        scheduled.append(coro)
        coro.close()

    runner._dispatch_action_sync = fake_dispatch_sync
    runner._schedule = fake_schedule
    runner._loop = SimpleNamespace(is_running=lambda: True)
    runner._runner = SimpleNamespace()
    runner._callback_card = FakeCallbackCard
    runner._callback_toast = FakeCallbackToast
    runner._callback_response = FakeCallbackResponse

    payload_history = SimpleNamespace(
        event=SimpleNamespace(
            operator=SimpleNamespace(open_id="ou_card"),
            context=SimpleNamespace(open_chat_id="oc_card", open_message_id="om_card"),
            action=SimpleNamespace(value={"action": _CARD_SESSION_HISTORY, "session_id": "session-123", "page": "1"}),
        )
    )
    payload_use = SimpleNamespace(
        event=SimpleNamespace(
            operator=SimpleNamespace(open_id="ou_card"),
            context=SimpleNamespace(open_chat_id="oc_card", open_message_id="om_card"),
            action=SimpleNamespace(value={"action": _CARD_SESSION_USE, "session_id": "session-123", "page": "1"}),
        )
    )

    history_response = runner._handle_card_action_sync(payload_history)
    use_response = runner._handle_card_action_sync(payload_use)

    assert history_response.toast.content == "已更新"
    assert use_response.toast.content == "已更新"
    assert len(scheduled) == 2


def test_feishu_live_progress_creates_then_updates_text_messages(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    created: list[str] = []

    async def fake_send_text_once(target, text: str) -> str:
        created.append(text)
        return f"om_{len(created)}"

    async def fake_send_text(target, text: str) -> None:
        created.extend(_chunk for _chunk in [text])

    runner._send_text_message_once = fake_send_text_once
    runner._send_text_message = fake_send_text

    async def scenario() -> None:
        progress = _FeishuLiveProgress(runner, runner._chat_target("oc_chat_1"), "测试请求")
        await progress.start()
        await progress.log("列出目录")
        await progress.reply("第一段回复")
        await progress.close(final_text="最终回复")

    asyncio.run(scenario())

    assert len(created) == 2
    assert created[0].startswith("过程 [已完成]\n测试请求\n• 列出目录")
    assert created[1] == "最终回复"


def test_feishu_live_progress_keeps_single_round_after_reply(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    created: list[str] = []

    async def fake_send_text_once(target, text: str) -> str:
        created.append(text)
        return f"om_{len(created)}"

    runner._send_text_message_once = fake_send_text_once

    async def scenario() -> None:
        progress = _FeishuLiveProgress(runner, runner._chat_target("oc_chat_1"), "测试请求")
        await progress.start()
        await progress.log("第一轮过程")
        await progress.reply("第一轮回复")
        await progress.log("第二轮过程")
        await asyncio.sleep(1.3)

    asyncio.run(scenario())

    assert created == ["过程 [进行中]\n测试请求\n• 第一轮过程\n• 第二轮过程"]


def test_feishu_live_progress_skips_tiny_reply_preview_until_more_complete(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    created: list[str] = []

    async def fake_send_text_once(target, text: str) -> str:
        created.append(text)
        return f"om_{len(created)}"

    runner._send_text_message_once = fake_send_text_once

    async def scenario() -> None:
        progress = _FeishuLiveProgress(runner, runner._chat_target("oc_chat_1"), "测试请求")
        await progress.start()
        await progress.reply("将")
        await progress.reply("将进行完整测试。")

    asyncio.run(scenario())

    assert created == []


def test_feishu_live_progress_sends_reply_in_segments_without_patch(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    created: list[str] = []

    async def fake_send_text_once(target, text: str) -> str:
        created.append(text)
        return f"om_{len(created)}"

    async def fake_send_text(target, text: str) -> None:
        created.extend(text.split("\u0000"))

    runner._send_text_message_once = fake_send_text_once
    runner._send_text_message = fake_send_text

    async def scenario() -> None:
        progress = _FeishuLiveProgress(runner, runner._chat_target("oc_chat_1"), "测试请求")
        await progress.start()
        await progress.reply("第一段已经完整了。\n第二行也有内容。")
        await progress.reply("第一段已经完整了。\n第二行也有内容。\n\n第三行继续补充，形成新的分段。")
        await progress.close(final_text="第一段已经完整了。\n第二行也有内容。\n\n第三行继续补充，形成新的分段。")

    asyncio.run(scenario())

    assert created == ["第一段已经完整了。\n第二行也有内容。\n\n第三行继续补充，形成新的分段。"]


def test_feishu_live_progress_sends_incremental_process_messages(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    created: list[str] = []

    async def fake_send_text_once(target, text: str) -> str:
        created.append(text)
        return f"om_{len(created)}"

    runner._send_text_message_once = fake_send_text_once

    async def scenario() -> None:
        progress = _FeishuLiveProgress(runner, runner._chat_target("oc_chat_1"), "测试请求")
        await progress.start()
        await progress.log("第一步")
        await progress.log("第二步")
        await asyncio.sleep(1.3)
        await progress.log("第三步")
        await progress.log("第四步")
        await asyncio.sleep(1.3)

    asyncio.run(scenario())

    assert created == [
        "过程 [进行中]\n测试请求\n• 第一步\n• 第二步",
        "过程补充\n• 第三步\n• 第四步",
    ]


def test_feishu_update_card_uses_patch_message_api(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    captured: dict[str, object] = {}

    class FakePatchBodyBuilder:
        def __init__(self) -> None:
            self.payload: dict[str, str] = {}

        def content(self, content: str):
            self.payload["content"] = content
            return self

        def build(self):
            return dict(self.payload)

    class FakePatchBody:
        @staticmethod
        def builder():
            return FakePatchBodyBuilder()

    class FakePatchRequestBuilder:
        def __init__(self) -> None:
            self.message_id_value = None
            self.body_value = None

        def message_id(self, message_id: str):
            self.message_id_value = message_id
            return self

        def request_body(self, request_body):
            self.body_value = request_body
            return self

        def build(self):
            return {"message_id": self.message_id_value, "body": self.body_value}

    class FakePatchRequest:
        @staticmethod
        def builder():
            return FakePatchRequestBuilder()

    class FakeResponse:
        def success(self) -> bool:
            return True

    def fake_patch(request):
        captured["request"] = request
        return FakeResponse()

    runner._patch_message_request_body = FakePatchBody
    runner._patch_message_request = FakePatchRequest
    runner._api = SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(message=SimpleNamespace(patch=fake_patch))))

    asyncio.run(runner._update_card_message("om_patch", "{\"ok\":true}"))

    assert captured["request"] == {
        "message_id": "om_patch",
        "body": {"content": "{\"ok\":true}"},
    }


def test_check_feishu_response_handles_dict_troubleshooter(caplog) -> None:
    class FakeResponse:
        code = 230099
        msg = "unsupported tag action"
        error = {"troubleshooter": "https://example.test/troubleshoot"}

        def success(self) -> bool:
            return False

        def get_troubleshooter(self):
            raise AttributeError("dict has no attribute troubleshooter")

        def get_log_id(self) -> str:
            return "log_123"

    with caplog.at_level("ERROR"):
        _check_feishu_response(FakeResponse(), "update_card")

    assert "Feishu API 调用失败 action=update_card" in caplog.text
    assert "https://example.test/troubleshoot" in caplog.text


def test_feishu_rendered_card_uses_legacy_interactive_structure(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)

    class FakeTaskRunner:
        def status_text(self, chat_key: str) -> str:
            return "后端状态: ready"

    runner._runner = FakeTaskRunner()
    card_json = runner._build_status_card(_FeishuActionContext(target=runner._chat_target("oc_chat_1"), open_id="ou_test", chat_id="oc_chat_1"))
    payload = json.loads(card_json)

    assert "schema" not in payload
    assert "elements" in payload
    assert payload["elements"][0]["tag"] == "div"
    assert any(item["tag"] == "action" for item in payload["elements"])


def test_feishu_bootstrap_initializes_task_runner_on_local_loop(make_settings, monkeypatch) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    runner._loop = asyncio.new_event_loop()
    calls: list[str] = []

    class FakeTaskRunner:
        def __init__(self, settings, send_message, open_live_progress=None) -> None:
            self._send_message = send_message
            self._open_live_progress = open_live_progress

        async def start(self) -> None:
            calls.append("runner.start")

    class FakeBuilder:
        def app_id(self, value: str):
            return self

        def app_secret(self, value: str):
            return self

        def build(self):
            return MagicMock()

    class FakeEventBuilder:
        def register_p2_im_message_receive_v1(self, handler):
            self.message_handler = handler
            return self

        def register_p2_application_bot_menu_v6(self, handler):
            self.menu_handler = handler
            return self

        def register_p2_card_action_trigger(self, handler):
            self.card_handler = handler
            return self

        def build(self):
            return object()

    class FakeLarkClient:
        @staticmethod
        def builder():
            return FakeBuilder()

    class FakeWsClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    fake_lark = SimpleNamespace(
        Client=FakeLarkClient,
        ws=SimpleNamespace(Client=FakeWsClient),
        EventDispatcherHandler=SimpleNamespace(builder=lambda encrypt_key, verification_token: FakeEventBuilder()),
    )

    class FakeCallbackCard:
        pass

    class FakeCallbackToast:
        pass

    class FakeCallbackResponse:
        def __init__(self) -> None:
            self.toast = None
            self.card = None

    monkeypatch.setattr("topilot.feishu_bot.TaskRunner", FakeTaskRunner)
    monkeypatch.setattr(
        "topilot.feishu_bot._safe_import_lark",
        lambda: {
            "lark": fake_lark,
            "log_level": SimpleNamespace(INFO="INFO"),
            "json": SimpleNamespace(marshal=lambda obj: json.dumps({}), unmarshal=lambda payload, cls: None),
            "message_type": SimpleNamespace(EVENT="event", CARD="card"),
            "ws_response": lambda code=200: SimpleNamespace(code=code, data=None),
            "create_message_request": object,
            "create_message_request_body": object,
            "patch_message_request": object,
            "patch_message_request_body": object,
            "reply_message_request": object,
            "reply_message_request_body": object,
            "callback_card": FakeCallbackCard,
            "callback_toast": FakeCallbackToast,
            "callback_response": FakeCallbackResponse,
        },
    )

    runner._bootstrap()

    assert calls == ["runner.start"]
    assert runner._runner is not None
    assert runner._client is not None
    runner._loop.close()
