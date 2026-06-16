from __future__ import annotations
"""Feishu 机器人接入层"""

import asyncio
import base64
import json
import logging
import threading
import time
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass
from uuid import uuid4

from topilot.config import Settings
from topilot.task_runner import ChatKey, TaskRunner

logger = logging.getLogger(__name__)

_MENU_STATUS = "topilot.status"
_MENU_MODEL = "topilot.model"
_MENU_SESSIONS = "topilot.sessions"
_MENU_SESSION_CURRENT = "topilot.session_current"
_MENU_SESSION_NEW = "topilot.session_new"
_MENU_WHOAMI = "topilot.whoami"

_CARD_STATUS = "topilot.card.status"
_CARD_MODEL = "topilot.card.model"
_CARD_SESSIONS = "topilot.card.sessions"
_CARD_SESSION_CURRENT = "topilot.card.session_current"
_CARD_SESSION_NEW = "topilot.card.session_new"
_CARD_WHOAMI = "topilot.card.whoami"
_CARD_MODEL_SET = "topilot.card.set_model"

_TEXT_COMMANDS = {
    "/start": _MENU_STATUS,
    "/status": _MENU_STATUS,
    "/model": _MENU_MODEL,
    "/sessions": _MENU_SESSIONS,
    "/session_current": _MENU_SESSION_CURRENT,
    "/session_new": _MENU_SESSION_NEW,
    "/whoami": _MENU_WHOAMI,
}


def _safe_import_lark():
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1.model.create_message_request import CreateMessageRequest
        from lark_oapi.api.im.v1.model.create_message_request_body import CreateMessageRequestBody
        from lark_oapi.api.im.v1.model.patch_message_request import PatchMessageRequest
        from lark_oapi.api.im.v1.model.patch_message_request_body import PatchMessageRequestBody
        from lark_oapi.api.im.v1.model.reply_message_request import ReplyMessageRequest
        from lark_oapi.api.im.v1.model.reply_message_request_body import ReplyMessageRequestBody
        from lark_oapi.core.enum import LogLevel
        from lark_oapi.core.json import JSON
        from lark_oapi.event.callback.model.p2_card_action_trigger import CallBackCard, CallBackToast, P2CardActionTriggerResponse
        from lark_oapi.ws.enum import MessageType
        from lark_oapi.ws.model import Response

        return {
            "lark": lark,
            "log_level": LogLevel,
            "json": JSON,
            "message_type": MessageType,
            "ws_response": Response,
            "create_message_request": CreateMessageRequest,
            "create_message_request_body": CreateMessageRequestBody,
            "patch_message_request": PatchMessageRequest,
            "patch_message_request_body": PatchMessageRequestBody,
            "reply_message_request": ReplyMessageRequest,
            "reply_message_request_body": ReplyMessageRequestBody,
            "callback_card": CallBackCard,
            "callback_toast": CallBackToast,
            "callback_response": P2CardActionTriggerResponse,
        }
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError("未安装 lark-oapi，无法启动 Feishu 机器人") from exc


def _feishu_is_allowed(settings: Settings, chat_id: str | None, open_id: str | None) -> bool:
    if settings.feishu_allowed_chat_ids and (chat_id or "") not in settings.feishu_allowed_chat_ids:
        return False
    if settings.feishu_allowed_open_ids and (open_id or "") not in settings.feishu_allowed_open_ids:
        return False
    return True


def _parse_text_content(content: str | None) -> str:
    if not content:
        return ""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content.strip()
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        post_text = _parse_post_content(payload)
        if post_text:
            return post_text
    return ""


def _parse_post_content(payload: object) -> str:
    root = _pick_post_root(payload)
    if not isinstance(root, dict):
        return ""

    lines: list[str] = []
    title = root.get("title")
    if isinstance(title, str) and title.strip():
        lines.append(title.strip())

    content = root.get("content")
    if isinstance(content, list):
        for block in content:
            line = _parse_post_block(block)
            if line:
                lines.append(line)

    if lines:
        return "\n".join(lines).strip()
    return _collect_text_fragments(root).strip()


def _pick_post_root(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload

    if isinstance(payload.get("content"), list):
        return payload

    for key in ("zh_cn", "en_us", "ja_jp"):
        candidate = payload.get(key)
        if isinstance(candidate, dict) and isinstance(candidate.get("content"), list):
            return candidate

    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get("content"), list):
            return value
    return payload


def _parse_post_block(block: object) -> str:
    if isinstance(block, list):
        line = "".join(_parse_post_inline(item) for item in block).strip()
        return line
    if isinstance(block, dict):
        return _parse_post_inline(block).strip()
    return ""


def _parse_post_inline(item: object) -> str:
    if not isinstance(item, dict):
        return str(item).strip() if isinstance(item, str) else ""

    tag = str(item.get("tag") or "").strip().lower()
    if tag in {"text", "a"}:
        text = item.get("text")
        return text.strip() if isinstance(text, str) else ""
    if tag == "at":
        for key in ("user_name", "name", "text"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    if tag == "img":
        return ""

    text = item.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return _collect_text_fragments(item)


def _collect_text_fragments(node: object) -> str:
    fragments: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                fragments.append(stripped)
            return
        if isinstance(value, list):
            for child in value:
                walk(child)
            return
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"tag", "href", "style", "un_escape"}:
                    continue
                walk(child)

    walk(node)
    return "\n".join(fragments)


def _chunk_text(text: str, limit: int = 1800) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]
    return chunks


def _trim_text(text: str, limit: int = 2400) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _button(label: str, action: str, *, kind: str = "default", **value: str) -> dict:
    payload = {"action": action}
    payload.update({key: val for key, val in value.items() if val})
    return {
        "tag": "button",
        "type": kind,
        "text": {"tag": "plain_text", "content": label},
        "value": payload,
    }


def _base_actions() -> list[list[dict]]:
    return [
        [
            _button("状态", _CARD_STATUS, kind="primary"),
            _button("模型", _CARD_MODEL),
            _button("会话", _CARD_SESSIONS),
        ],
        [
            _button("当前会话", _CARD_SESSION_CURRENT),
            _button("新建会话", _CARD_SESSION_NEW),
            _button("我的 ID", _CARD_WHOAMI),
        ],
    ]


def _render_card(title: str, body: str, *, subtitle: str | None = None, actions: list[list[dict]] | None = None, template: str = "blue") -> str:
    header_title = title if not subtitle else f"{title}\n{subtitle}"
    elements: list[dict] = [{"tag": "div", "text": {"tag": "lark_md", "content": body}}]
    if actions:
        for row in actions:
            if row:
                elements.append({"tag": "action", "actions": row})
    payload = {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": header_title},
        },
        "elements": elements,
    }
    return json.dumps(payload, ensure_ascii=False)


def _extract_message_id(response) -> str | None:
    data = getattr(response, "data", None)
    message_id = getattr(data, "message_id", None)
    return str(message_id) if message_id else None


def _check_feishu_response(response, action: str) -> None:
    if response is None:
        logger.error("Feishu API 返回空响应 action=%s", action)
        return
    success = getattr(response, "success", None)
    is_ok = bool(success()) if callable(success) else False
    if is_ok:
        return
    troubleshooter = None
    if hasattr(response, "get_troubleshooter"):
        try:
            troubleshooter = response.get_troubleshooter()
        except Exception:
            error_obj = getattr(response, "error", None)
            if isinstance(error_obj, dict):
                troubleshooter = error_obj.get("troubleshooter")
    logger.error(
        "Feishu API 调用失败 action=%s code=%s msg=%s log_id=%s troubleshooter=%s",
        action,
        getattr(response, "code", None),
        getattr(response, "msg", None),
        response.get_log_id() if hasattr(response, "get_log_id") else None,
        troubleshooter,
    )


@dataclass(slots=True)
class _FeishuTarget:
    receive_id_type: str
    receive_id: str
    session_key: str


@dataclass(slots=True)
class _FeishuActionContext:
    target: _FeishuTarget
    open_id: str
    chat_id: str | None = None
    message_id: str | None = None


class FeishuBotRunner:
    """Feishu 长连接机器人运行器"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._runner: TaskRunner | None = None
        self._loop = asyncio.new_event_loop()
        self._thread: threading.Thread | None = None
        self._client = None
        self._lark = None
        self._json = None
        self._api = None
        self._log_level = None
        self._message_type = None
        self._ws_response = None
        self._callback_card = None
        self._callback_toast = None
        self._callback_response = None
        self._create_message_request = None
        self._create_message_request_body = None
        self._patch_message_request = None
        self._patch_message_request_body = None
        self._reply_message_request = None
        self._reply_message_request_body = None

    def start_background(self) -> None:
        self._thread = threading.Thread(target=self._run, name="topilot-feishu", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._bootstrap()
        assert self._client is not None
        self._client.start()

    def _on_event_task_done(self, future: asyncio.Future | ConcurrentFuture) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("Feishu 消息处理失败")

    def _schedule(self, coroutine) -> None:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
            future.add_done_callback(self._on_event_task_done)
            return

        if running_loop is self._loop:
            task = self._loop.create_task(coroutine)
            task.add_done_callback(self._on_event_task_done)
            return

        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        future.add_done_callback(self._on_event_task_done)

    def _bootstrap(self) -> None:
        imported = _safe_import_lark()
        self._lark = imported["lark"]
        self._log_level = imported["log_level"]
        self._json = imported["json"]
        self._message_type = imported["message_type"]
        self._ws_response = imported["ws_response"]
        self._callback_card = imported["callback_card"]
        self._callback_toast = imported["callback_toast"]
        self._callback_response = imported["callback_response"]
        self._create_message_request = imported["create_message_request"]
        self._create_message_request_body = imported["create_message_request_body"]
        self._patch_message_request = imported["patch_message_request"]
        self._patch_message_request_body = imported["patch_message_request_body"]
        self._reply_message_request = imported["reply_message_request"]
        self._reply_message_request_body = imported["reply_message_request_body"]

        self._api = (
            self._lark.Client.builder()
            .app_id(self._settings.feishu_app_id or "")
            .app_secret(self._settings.feishu_app_secret or "")
            .build()
        )

        async def send_message(chat_key: ChatKey, text: str) -> None:
            target = self._target_from_chat_key(str(chat_key))
            await self._send_result_message(target, text)

        async def open_live_progress(chat_key: ChatKey, title: str) -> "_FeishuLiveProgress":
            target = self._target_from_chat_key(str(chat_key))
            progress = _FeishuLiveProgress(self, target, title)
            return await progress.start()

        self._runner = TaskRunner(self._settings, send_message, open_live_progress=open_live_progress)
        self._loop.run_until_complete(self._runner.start())

        def handle_message_event(data) -> None:
            self._schedule(self._handle_message_event(data))

        def handle_menu_event(data):
            return self._handle_menu_event_sync(data)

        def handle_card_action(data):
            return self._handle_card_action_sync(data)

        event_handler = (
            self._lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(handle_message_event)
            .register_p2_application_bot_menu_v6(handle_menu_event)
            .register_p2_card_action_trigger(handle_card_action)
            .build()
        )
        self._client = self._build_ws_client(event_handler)

    def _build_ws_client(self, event_handler):
        parent_client = self._lark.ws.Client
        message_type_enum = self._message_type
        json_codec = self._json
        response_type = self._ws_response

        class TopilotWsClient(parent_client):
            async def _handle_data_frame(self, frame):  # type: ignore[override]
                def _header(key: str) -> str:
                    for header in frame.headers:
                        if header.key == key:
                            return header.value
                    raise KeyError(key)

                msg_id = _header("message_id")
                trace_id = _header("trace_id")
                sum_ = _header("sum")
                seq = _header("seq")
                type_ = _header("type")

                payload = frame.payload
                if int(sum_) > 1:
                    payload = self._combine(msg_id, int(sum_), int(seq), payload)
                    if payload is None:
                        return

                message_type = message_type_enum(type_)
                logger.debug(
                    self._fmt_log(
                        "receive message, message_type: {}, message_id: {}, trace_id: {}",
                        message_type.value,
                        msg_id,
                        trace_id,
                    )
                )

                if message_type not in {message_type_enum.EVENT, message_type_enum.CARD}:
                    return

                response = response_type(code=200)
                try:
                    start_ms = int(round(time.time() * 1000))
                    result = self._event_handler._do_without_validation(payload)
                    end_ms = int(round(time.time() * 1000))
                    header = frame.headers.add()
                    header.key = "biz_rt"
                    header.value = str(end_ms - start_ms)
                    if result is not None:
                        response.data = base64.b64encode(json_codec.marshal(result).encode("utf-8"))
                except Exception as exc:
                    logger.error(
                        self._fmt_log(
                            "handle message failed, message_type: {}, message_id: {}, trace_id: {}, err: {}",
                            message_type.value,
                            msg_id,
                            trace_id,
                            exc,
                        )
                    )
                    response = response_type(code=500)

                frame.payload = json_codec.marshal(response).encode("utf-8")
                await self._write_message(frame.SerializeToString())

        return TopilotWsClient(
            app_id=self._settings.feishu_app_id or "",
            app_secret=self._settings.feishu_app_secret or "",
            event_handler=event_handler,
            log_level=self._log_level.INFO,
        )

    def _target_from_chat_key(self, chat_key: str) -> _FeishuTarget:
        if chat_key.startswith("feishu-open:"):
            receive_id = chat_key.removeprefix("feishu-open:")
            return _FeishuTarget(receive_id_type="open_id", receive_id=receive_id, session_key=chat_key)
        receive_id = chat_key.removeprefix("feishu:")
        return _FeishuTarget(receive_id_type="chat_id", receive_id=receive_id, session_key=f"feishu:{receive_id}")

    def _chat_target(self, chat_id: str) -> _FeishuTarget:
        return _FeishuTarget(receive_id_type="chat_id", receive_id=chat_id, session_key=f"feishu:{chat_id}")

    def _open_target(self, open_id: str) -> _FeishuTarget:
        return _FeishuTarget(receive_id_type="open_id", receive_id=open_id, session_key=f"feishu-open:{open_id}")

    async def _handle_message_event(self, data) -> None:
        if self._runner is None:
            return

        event = getattr(data, "event", None)
        sender = getattr(event, "sender", None)
        message = getattr(event, "message", None)
        if message is None:
            return

        message_type = str(getattr(message, "message_type", "") or "")
        if message_type not in {"text", "post"}:
            logger.info("忽略 Feishu 非受支持消息 message_type=%s", message_type or "<none>")
            return

        sender_id = getattr(sender, "sender_id", None)
        open_id = str(getattr(sender_id, "open_id", "") or "")
        chat_id = str(getattr(message, "chat_id", "") or "")
        message_id = str(getattr(message, "message_id", "") or "")
        text = _parse_text_content(getattr(message, "content", None))
        if not text:
            logger.info(
                "Feishu 消息未提取到可执行文本 message_type=%s chat_id=%s open_id=%s",
                message_type or "<none>",
                chat_id or "<none>",
                open_id or "<none>",
            )
            return

        if not _feishu_is_allowed(self._settings, chat_id, open_id):
            logger.warning("未授权 Feishu 访问 chat_id=%s open_id=%s", chat_id, open_id)
            await self._reply_permission_denied(message_id)
            return

        command_result = await self._try_handle_text_command(self._chat_target(chat_id), chat_id, open_id, text)
        if command_result:
            return

        logger.info(
            "收到 Feishu 消息 chat_id=%s open_id=%s message_type=%s len=%s",
            chat_id,
            open_id or "<none>",
            message_type,
            len(text),
        )
        await self._runner.submit(f"feishu:{chat_id}", text)

    async def _handle_menu_event(self, data) -> None:
        event = getattr(data, "event", None)
        if event is None:
            return

        operator = getattr(event, "operator", None)
        operator_id = getattr(operator, "operator_id", None)
        open_id = str(getattr(operator_id, "open_id", "") or "")
        event_key = str(getattr(event, "event_key", "") or "")
        logger.info("收到 Feishu 菜单事件 open_id=%s event_key=%s", open_id or "<none>", event_key or "<none>")
        if not open_id:
            logger.info("忽略无法定位 open_id 的 Feishu 菜单事件 event_key=%s", event_key or "<none>")
            return
        if not _feishu_is_allowed(self._settings, None, open_id):
            logger.warning("未授权 Feishu 菜单访问 open_id=%s", open_id)
            await self._send_text_message(self._open_target(open_id), "当前用户未授权，请联系维护者配置飞书白名单")
            return
        await self._dispatch_action(_FeishuActionContext(target=self._open_target(open_id), open_id=open_id), event_key)

    def _handle_menu_event_sync(self, data):
        self._schedule(self._handle_menu_event(data))
        return {}

    def _handle_card_action_sync(self, data):
        try:
            return self._build_card_action_callback_response(data)
        except Exception:
            logger.exception("Feishu 卡片动作处理失败")
            return self._build_card_action_response("操作失败，请稍后重试")

    async def _handle_card_action(self, data):
        return self._build_card_action_callback_response(data)

    def _build_card_action_callback_response(self, data):
        event = getattr(data, "event", None)
        operator = getattr(event, "operator", None)
        context = getattr(event, "context", None)
        action = getattr(event, "action", None)
        value = getattr(action, "value", None) or {}
        action_name = str(value.get("action") or "")
        model = str(value.get("model") or "")
        open_id = str(getattr(operator, "open_id", "") or "")
        chat_id = str(getattr(context, "open_chat_id", "") or "")
        message_id = str(getattr(context, "open_message_id", "") or "")
        logger.info(
            "收到 Feishu 卡片动作 action=%s model=%s chat_id=%s open_id=%s message_id=%s",
            action_name or "<none>",
            model or "<none>",
            chat_id or "<none>",
            open_id or "<none>",
            message_id or "<none>",
        )
        if not chat_id or not _feishu_is_allowed(self._settings, chat_id, open_id):
            return self._build_card_action_response("当前用户未授权")

        card_json = self._dispatch_action_sync(
            _FeishuActionContext(
                target=self._chat_target(chat_id),
                open_id=open_id,
                chat_id=chat_id,
                message_id=message_id,
            ),
            action_name,
            model=model,
        )
        return self._build_card_action_response("已更新", card_json)

    def _build_card_action_response(self, toast_text: str, card_json: str | None = None):
        toast = self._callback_toast()
        toast.type = "info"
        toast.content = toast_text
        response = self._callback_response()
        response.toast = toast
        if card_json:
            card = self._callback_card()
            card.type = "raw"
            card.data = json.loads(card_json)
            response.card = card
        return response

    async def _reply_permission_denied(self, message_id: str) -> None:
        if not message_id:
            return
        body = (
            self._reply_message_request_body.builder()
            .content(json.dumps({"text": "当前用户未授权，请将 chat_id 或 open_id 加入 Feishu 白名单配置"}, ensure_ascii=False))
            .msg_type("text")
            .reply_in_thread(self._settings.feishu_reply_in_thread)
            .uuid(str(uuid4()))
            .build()
        )
        request = (
            self._reply_message_request.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )
        response = await asyncio.to_thread(self._api.im.v1.message.reply, request)
        _check_feishu_response(response, "reply_permission_denied")

    async def _send_text_message(self, target: _FeishuTarget, text: str) -> None:
        for chunk in _chunk_text(text):
            body = (
                self._create_message_request_body.builder()
                .receive_id(target.receive_id)
                .msg_type("text")
                .content(json.dumps({"text": chunk}, ensure_ascii=False))
                .uuid(str(uuid4()))
                .build()
            )
            request = (
                self._create_message_request.builder()
                .receive_id_type(target.receive_id_type)
                .request_body(body)
                .build()
            )
            response = await asyncio.to_thread(self._api.im.v1.message.create, request)
            _check_feishu_response(response, f"send_text:{target.receive_id_type}")

    async def _send_card_message(self, target: _FeishuTarget, card_json: str) -> str | None:
        body = (
            self._create_message_request_body.builder()
            .receive_id(target.receive_id)
            .msg_type("interactive")
            .content(card_json)
            .uuid(str(uuid4()))
            .build()
        )
        request = (
            self._create_message_request.builder()
            .receive_id_type(target.receive_id_type)
            .request_body(body)
            .build()
        )
        response = await asyncio.to_thread(self._api.im.v1.message.create, request)
        _check_feishu_response(response, f"send_card:{target.receive_id_type}")
        return _extract_message_id(response)

    async def _update_card_message(self, message_id: str, card_json: str) -> None:
        if not message_id:
            return
        body = (
            self._patch_message_request_body.builder()
            .content(card_json)
            .build()
        )
        request = (
            self._patch_message_request.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )
        response = await asyncio.to_thread(self._api.im.v1.message.patch, request)
        _check_feishu_response(response, "update_card")

    async def _send_or_update_card(self, context: _FeishuActionContext, card_json: str) -> str | None:
        if context.message_id:
            await self._update_card_message(context.message_id, card_json)
            return context.message_id
        return await self._send_card_message(context.target, card_json)

    async def _send_result_message(self, target: _FeishuTarget, text: str) -> None:
        card_json = _render_card(
            "Topilot 回复",
            _trim_text(text, limit=3000),
            subtitle="Feishu 模式",
            actions=_base_actions(),
            template="green",
        )
        await self._send_card_message(target, card_json)

    def _build_status_card(self, context: _FeishuActionContext) -> str:
        assert self._runner is not None
        return _render_card(
            "Topilot 状态",
            self._runner.status_text(context.target.session_key),
            subtitle="Feishu 模式",
            actions=_base_actions(),
            template="blue",
        )

    def _build_model_card(self, context: _FeishuActionContext, prefix: str | None = None) -> str:
        assert self._runner is not None
        current = self._runner.current_model(context.target.session_key)
        models = self._runner.list_models()
        lines = [f"当前模型: {current}"]
        if prefix:
            lines.insert(0, prefix)
            lines.insert(1, "")
        if models:
            lines.extend(["", "可用模型:"])
            lines.extend(f"- {model}" for model in models[:12])
        actions = _base_actions()
        if models:
            model_rows: list[list[dict]] = []
            row: list[dict] = []
            for model in models[:6]:
                row.append(
                    _button(
                        f"{'✓ ' if model == current else ''}{model}",
                        _CARD_MODEL_SET,
                        kind="primary" if model == current else "default",
                        model=model,
                    )
                )
                if len(row) == 2:
                    model_rows.append(row)
                    row = []
            if row:
                model_rows.append(row)
            actions = model_rows + actions
        return _render_card("模型切换", "\n".join(lines), subtitle="点击按钮直接切换", actions=actions, template="indigo")

    def _build_sessions_card(self, context: _FeishuActionContext, prefix: str | None = None) -> str:
        assert self._runner is not None
        body = self._runner.session_list_text(context.target.session_key)
        if prefix:
            body = f"{prefix}\n\n{body}"
        actions = [
            [
                _button("当前会话", _CARD_SESSION_CURRENT, kind="primary"),
                _button("新建会话", _CARD_SESSION_NEW),
            ]
        ] + _base_actions()
        return _render_card("会话管理", body, subtitle="Feishu 模式", actions=actions, template="turquoise")

    def _build_session_current_card(self, context: _FeishuActionContext, prefix: str | None = None) -> str:
        assert self._runner is not None
        body = self._runner.session_current_text(context.target.session_key)
        if prefix:
            body = f"{prefix}\n\n{body}"
        return _render_card("当前会话", body, subtitle="Feishu 模式", actions=_base_actions(), template="turquoise")

    def _build_whoami_card(self, context: _FeishuActionContext) -> str:
        body = f"open_id: {context.open_id or '<none>'}"
        if context.chat_id:
            body += f"\nchat_id: {context.chat_id}"
        body += f"\nsession_key: {context.target.session_key}"
        return _render_card("身份信息", body, subtitle="Feishu 诊断", actions=_base_actions(), template="wathet")

    async def _dispatch_action(
        self,
        context: _FeishuActionContext,
        action: str,
        *,
        model: str | None = None,
        return_card: bool = False,
    ) -> str | None:
        if self._runner is None:
            return None

        if action in {_MENU_STATUS, _CARD_STATUS}:
            card_json = self._build_status_card(context)
        elif action in {_MENU_MODEL, _CARD_MODEL}:
            card_json = self._build_model_card(context)
        elif action == _CARD_MODEL_SET:
            normalized = (model or "").strip()
            available = self._runner.list_models()
            if normalized and normalized in available:
                self._runner.set_model(context.target.session_key, normalized)
                card_json = self._build_model_card(context, prefix=f"已切换模型: {normalized}")
            else:
                card_json = self._build_model_card(context, prefix="模型不可用，未执行切换")
        elif action in {_MENU_SESSIONS, _CARD_SESSIONS}:
            card_json = self._build_sessions_card(context)
        elif action in {_MENU_SESSION_CURRENT, _CARD_SESSION_CURRENT}:
            card_json = self._build_session_current_card(context)
        elif action in {_MENU_SESSION_NEW, _CARD_SESSION_NEW}:
            result = self._runner.session_new_text(context.target.session_key)
            card_json = self._build_session_current_card(context, prefix=result)
        elif action in {_MENU_WHOAMI, _CARD_WHOAMI}:
            card_json = self._build_whoami_card(context)
        else:
            return None

        if return_card:
            return card_json
        await self._send_or_update_card(context, card_json)
        return card_json

    def _dispatch_action_sync(
        self,
        context: _FeishuActionContext,
        action: str,
        *,
        model: str | None = None,
    ) -> str | None:
        if self._runner is None:
            return None

        if action in {_MENU_STATUS, _CARD_STATUS}:
            return self._build_status_card(context)
        if action in {_MENU_MODEL, _CARD_MODEL}:
            return self._build_model_card(context)
        if action == _CARD_MODEL_SET:
            normalized = (model or "").strip()
            available = self._runner.list_models()
            if normalized and normalized in available:
                self._runner.set_model(context.target.session_key, normalized)
                return self._build_model_card(context, prefix=f"已切换模型: {normalized}")
            return self._build_model_card(context, prefix="模型不可用，未执行切换")
        if action in {_MENU_SESSIONS, _CARD_SESSIONS}:
            return self._build_sessions_card(context)
        if action in {_MENU_SESSION_CURRENT, _CARD_SESSION_CURRENT}:
            return self._build_session_current_card(context)
        if action in {_MENU_SESSION_NEW, _CARD_SESSION_NEW}:
            result = self._runner.session_new_text(context.target.session_key)
            return self._build_session_current_card(context, prefix=result)
        if action in {_MENU_WHOAMI, _CARD_WHOAMI}:
            return self._build_whoami_card(context)
        return None

    async def _try_handle_text_command(self, target: _FeishuTarget, chat_id: str, open_id: str, text: str) -> bool:
        normalized = text.strip()
        if normalized.startswith("/session_use "):
            if self._runner is None:
                return True
            session_prefix = normalized.split(maxsplit=1)[1].strip()
            result = self._runner.session_use_text(target.session_key, session_prefix)
            context = _FeishuActionContext(target=target, open_id=open_id, chat_id=chat_id)
            card_json = self._build_session_current_card(context, prefix=result)
            await self._send_or_update_card(context, card_json)
            return True

        action = _TEXT_COMMANDS.get(normalized)
        if not action:
            return False
        await self._dispatch_action(_FeishuActionContext(target=target, open_id=open_id, chat_id=chat_id), action)
        return True


class _FeishuLiveProgress:
    """Feishu 端流式展示实现"""

    def __init__(self, bot: FeishuBotRunner, target: _FeishuTarget, title: str) -> None:
        self._bot = bot
        self._target = target
        self._title = title
        self._message_id: str | None = None
        self._progress_lines: list[str] = []
        self._reply_buffer = ""
        self._reply_started = False
        self._closed = False
        self._last_render = ""
        self._last_flush_at = 0.0
        self._flush_task: asyncio.Task[None] | None = None

    async def start(self) -> "_FeishuLiveProgress":
        card_json = self._render_card("进行中")
        self._message_id = await self._bot._send_card_message(self._target, card_json)
        self._last_render = card_json
        self._last_flush_at = time.monotonic()
        return self

    async def log(self, text: str) -> None:
        normalized = text.strip()
        if not normalized or self._closed:
            return
        if self._should_skip_log(normalized):
            return
        if self._reply_started:
            await self._roll_to_next_round()
        self._merge_progress_line(normalized)
        await self._schedule_flush()

    async def reply(self, text: str) -> None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if normalized == "" or self._closed:
            return
        self._reply_started = True
        self._append_reply_chunk(normalized)
        await self._schedule_flush()

    async def close(self, final_text: str | None = None, failed: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        if final_text and final_text.strip():
            final_clean = final_text.replace("\r\n", "\n").replace("\r", "\n").strip()
            if final_clean != self._reply_text():
                self._reply_buffer = final_clean
        if failed:
            self._progress_lines.append("执行失败")
        await self._flush(force=True)
        await self._cancel_task(self._flush_task)

    async def _roll_to_next_round(self) -> None:
        self._progress_lines = []
        self._reply_buffer = ""
        self._reply_started = False
        await self._flush(force=True)

    def _render_card(self, state: str) -> str:
        progress_lines = self._progress_lines[-10:] or ["处理中..."]
        lines = [f"状态: {state}", "", "过程:"]
        lines.extend(f"- {line}" for line in progress_lines)
        reply_text = self._reply_text()
        if reply_text:
            lines.extend(["", "回复:", _trim_text(reply_text, limit=2800)])
        return _render_card(
            self._title,
            "\n".join(lines),
            subtitle="Feishu 流式进度",
            actions=_base_actions(),
            template="blue",
        )

    async def _schedule_flush(self) -> None:
        if self._can_flush_now():
            await self._flush(force=True)
            return
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self) -> None:
        await asyncio.sleep(0.9)
        await self._flush(force=True)

    async def _flush(self, force: bool = False) -> None:
        card_json = self._render_card("已完成" if self._closed else "进行中")
        if card_json == self._last_render and not force:
            return
        self._last_render = card_json
        self._last_flush_at = time.monotonic()
        if self._message_id:
            await self._bot._update_card_message(self._message_id, card_json)
        else:
            self._message_id = await self._bot._send_card_message(self._target, card_json)

    def _merge_progress_line(self, line: str) -> None:
        if not self._progress_lines:
            self._progress_lines.append(line)
            return
        last = self._progress_lines[-1]
        if last == line:
            self._progress_lines[-1] = f"{line} × 2"
            return
        if last.startswith(f"{line} × "):
            count_text = last.split(" × ")[-1].strip()
            count = int(count_text) if count_text.isdigit() else 1
            self._progress_lines[-1] = f"{line} × {count + 1}"
            return
        self._progress_lines.append(line)
        if len(self._progress_lines) > 60:
            self._progress_lines = self._progress_lines[-60:]

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

    def _reply_text(self) -> str:
        return self._reply_buffer.rstrip()

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
        return all(char in punctuation for char in chunk)

    def _should_skip_log(self, line: str) -> bool:
        lowered = line.lower()
        noisy = (
            "[session.tools_updated]",
            "[user.message]",
            "report_intent",
            "[subagent.completed]",
        )
        return any(flag in lowered for flag in noisy)

    def _can_flush_now(self) -> bool:
        return (time.monotonic() - self._last_flush_at) >= 0.9

    async def _cancel_task(self, task: asyncio.Task[None] | None) -> None:
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def start_feishu_bot(settings: Settings) -> FeishuBotRunner:
    """启动 Feishu 机器人后台线程并返回运行器"""

    runner = FeishuBotRunner(settings)
    runner.start_background()
    logger.info("Feishu bot 后台线程已启动")
    return runner
