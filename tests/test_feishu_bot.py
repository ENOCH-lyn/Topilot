from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from topilot.feishu_bot import (
    _FeishuActionContext,
    _FeishuLiveProgress,
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

    def fake_dispatch_sync(context, action: str, *, model: str | None = None):
        assert context.target.session_key == "feishu:oc_card"
        assert context.message_id == "om_card"
        assert action == _CARD_STATUS
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

    def fake_dispatch_sync(context, action: str, *, model: str | None = None):
        captured.append((action, model))
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


def test_feishu_live_progress_creates_then_updates_card(make_settings) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    runner = FeishuBotRunner(settings)
    sent: list[str] = []
    updated: list[tuple[str, str]] = []

    async def fake_send_card(target, card_json: str) -> str:
        sent.append(card_json)
        return "om_progress"

    async def fake_update_card(message_id: str, card_json: str) -> None:
        updated.append((message_id, card_json))

    runner._send_card_message = fake_send_card
    runner._update_card_message = fake_update_card

    async def scenario() -> None:
        progress = _FeishuLiveProgress(runner, runner._chat_target("oc_chat_1"), "测试请求")
        await progress.start()
        await progress.log("列出目录")
        await progress.reply("第一段回复")
        await progress.close(final_text="最终回复")

    asyncio.run(scenario())

    assert len(sent) == 1
    assert "测试请求" in sent[0]
    assert updated
    assert updated[-1][0] == "om_progress"
    assert "最终回复" in updated[-1][1]


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
