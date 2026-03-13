from __future__ import annotations

import asyncio
from asyncio.subprocess import Process
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeAlias

from copilot_in_telegram.agent import AssistantPlanner
from copilot_in_telegram.config import Settings
from copilot_in_telegram.conversation_store import ConversationStore
from copilot_in_telegram.session_store import SessionStore
from copilot_in_telegram.models import ActionType, EventType, NotificationEvent, TaskRecord, TaskState
from copilot_in_telegram.policy import NotificationPolicy
from copilot_in_telegram.store import TaskStore

ButtonList: TypeAlias = list[tuple[str, str]]
SendMessage = Callable[[int, str, ButtonList | None], Awaitable[None]]


class LiveProgress(Protocol):
    async def log(self, text: str) -> None: ...

    async def reply(self, text: str) -> None: ...

    async def close(self, final_text: str | None = None, failed: bool = False) -> None: ...


OpenLiveProgress = Callable[[int, str], Awaitable[LiveProgress]]


class CommandExecutionError(RuntimeError):
    pass


class BrowserAutomationError(RuntimeError):
    pass


def _shell_command(default_shell: str, command: str) -> list[str]:
    shell = default_shell.strip().lower()
    if shell in {"powershell", "pwsh", "powershell.exe", "pwsh.exe"}:
        executable = "pwsh" if shell.startswith("pwsh") else "powershell"
        return [executable, "-NoProfile", "-NonInteractive", "-Command", command]
    if shell in {"cmd", "cmd.exe"}:
        return ["cmd", "/c", command]
    return [default_shell, "-c", command]


async def run_shell(
    default_shell: str,
    command: str,
    timeout_seconds: int,
    cancel_event: asyncio.Event,
) -> tuple[int, str, str]:
    argv = _shell_command(default_shell, command)
    process: Process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    communicate_task = asyncio.create_task(process.communicate())
    cancel_task = asyncio.create_task(cancel_event.wait())

    try:
        done, _ = await asyncio.wait(
            {communicate_task, cancel_task},
            timeout=max(timeout_seconds, 1),
            return_when=asyncio.FIRST_COMPLETED,
        )

        if communicate_task in done:
            stdout_bytes, stderr_bytes = communicate_task.result()
            return process.returncode or 0, stdout_bytes.decode("utf-8", errors="replace"), stderr_bytes.decode(
                "utf-8", errors="replace"
            )

        if cancel_task in done and cancel_event.is_set():
            process.terminate()
            await process.wait()
            return 130, "", "任务已被用户打断"

        process.kill()
        await process.wait()
        return 124, "", f"命令执行超时（>{timeout_seconds}s）"
    finally:
        if not communicate_task.done():
            communicate_task.cancel()
        if not cancel_task.done():
            cancel_task.cancel()


def summarize_command_result(returncode: int, stdout: str, stderr: str, max_chars: int = 1200) -> str:
    out = (stdout or "").strip()
    err = (stderr or "").strip()
    parts = [f"exit={returncode}"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err}")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        return text[:max_chars] + "\n...(truncated)"
    return text


async def open_and_describe(url: str) -> str:
    return f"浏览器能力当前为占位实现，收到 URL: {url}"


class TaskRunner:
    def __init__(self, settings: Settings, send_message: SendMessage, open_live_progress: OpenLiveProgress | None = None) -> None:
        self._settings = settings
        self._send_message = send_message
        self._open_live_progress = open_live_progress
        self._store = TaskStore(settings.task_db_path)
        self._conversation = ConversationStore(settings.chat_db_path)
        self._sessions = SessionStore(settings.session_db_path)
        self._planner = AssistantPlanner(settings)
        self._policy = NotificationPolicy()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._cancel_events: dict[str, asyncio.Event] = {}

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker(), name="task-runner-worker")

    async def submit(self, chat_id: int, instruction: str) -> TaskRecord:
        history = self._conversation.recent(chat_id)
        active_session_id = self._sessions.ensure_active_session(chat_id)
        self._sessions.touch(chat_id, active_session_id)
        live_progress = await self._start_live_progress(chat_id, instruction)
        try:
            plan = await self._planner.plan(
                active_session_id,
                history,
                instruction,
                progress_logger=live_progress.log if live_progress else None,
                reply_streamer=live_progress.reply if live_progress else None,
            )
        except Exception:
            if live_progress:
                await live_progress.close(failed=True)
            raise
        self._conversation.append_turn(chat_id, "user", instruction)

        if plan.action_type is ActionType.RESPOND_ONLY:
            if plan.reasoning_message and self._settings.copilot_cli_forward_reasoning:
                if live_progress is None:
                    await self._send_message(chat_id, f"[思考过程]\n{plan.reasoning_message}")
            reply = plan.assistant_message or self._planner.fallback_response()
            self._conversation.append_turn(chat_id, "assistant", reply)
            if live_progress:
                await live_progress.close(final_text=reply)
            else:
                await self._send_message(chat_id, reply)
            return TaskRecord(
                chat_id=chat_id,
                instruction=instruction,
                state=TaskState.COMPLETED,
                summary=plan.summary,
                result_summary=reply,
            )

        if live_progress:
            await live_progress.close(final_text=plan.summary or "已转入任务执行阶段")

        task = TaskRecord(chat_id=chat_id, instruction=instruction)
        task.summary = plan.summary
        task.command = plan.command
        task.url = plan.url
        task.touch()

        self._store.upsert(task)
        await self._notify(NotificationEvent(EventType.ACCEPTED, task))

        if plan.requires_approval:
            task.state = TaskState.PENDING_APPROVAL
            self._store.upsert(task)
            await self._notify(NotificationEvent(EventType.APPROVAL_REQUIRED, task))
            return task

        self._store.upsert(task)
        await self._queue.put(task.id)
        return task

    async def _start_live_progress(self, chat_id: int, instruction: str) -> LiveProgress | None:
        if self._open_live_progress is None or not self._settings.copilot_cli_enabled:
            return None
        title = instruction.strip() or "Copilot 请求"
        if len(title) > 80:
            title = title[:80] + "..."
        return await self._open_live_progress(chat_id, title)

    async def approve(self, chat_id: int, task_id: str) -> str:
        task = self._require_chat_task(chat_id, task_id)
        if task.state is not TaskState.PENDING_APPROVAL:
            return f"任务 {task.id} 当前状态为 {task.state}，不能再批准。"
        task.state = TaskState.RECEIVED
        task.touch()
        self._store.upsert(task)
        await self._queue.put(task.id)
        return f"任务 {task.id} 已批准，准备执行。"

    async def deny(self, chat_id: int, task_id: str) -> str:
        task = self._require_chat_task(chat_id, task_id)
        if task.state is not TaskState.PENDING_APPROVAL:
            return f"任务 {task.id} 当前状态为 {task.state}，不能拒绝。"
        task.state = TaskState.REJECTED
        task.touch()
        self._store.upsert(task)
        await self._notify(NotificationEvent(EventType.REJECTED, task))
        return f"任务 {task.id} 已拒绝。"

    async def interrupt(self, chat_id: int, task_id: str | None = None) -> str:
        target = None
        if task_id:
            task = self._require_chat_task(chat_id, task_id)
            if task.state is TaskState.RUNNING:
                target = task
        else:
            for item in self._store.list_for_chat(chat_id, limit=20):
                if item.state is TaskState.RUNNING:
                    target = item
                    break

        if target is None:
            return "当前没有可打断的运行中任务。"

        cancel_event = self._cancel_events.get(target.id)
        if cancel_event is None:
            return f"任务 {target.id} 当前不可打断（可能已接近完成）。"
        cancel_event.set()
        return f"已请求打断任务 {target.id}。"

    def history_text(self, chat_id: int) -> str:
        tasks = self._store.list_for_chat(chat_id, limit=8)
        if not tasks:
            return "暂无任务记录。"
        lines = []
        for task in tasks:
            lines.append(f"{task.id} | {task.state} | {task.instruction}")
        return "最近任务:\n" + "\n".join(lines)

    def status_text(self, chat_id: int) -> str:
        tasks = self._store.list_for_chat(chat_id, limit=5)
        if not tasks:
            return "当前没有任务。"
        head = tasks[0]
        return (
            f"最近任务 {head.id}\n"
            f"状态: {head.state}\n"
            f"摘要: {head.summary or head.instruction}\n"
            f"结果: {head.result_summary or '尚无'}"
        )

    def reset_text(self, chat_id: int) -> str:
        self._conversation.reset_chat(chat_id)
        return "当前 chat 的会话记忆已清空。"

    def llm_status_text(self) -> str:
        return self._planner.llm_status_text()

    def session_current_text(self, chat_id: int) -> str:
        session_id = self._sessions.ensure_active_session(chat_id)
        return f"当前 Copilot 会话: {session_id}"

    def session_list_text(self, chat_id: int) -> str:
        sessions = self._sessions.list_sessions(chat_id, limit=12)
        if not sessions:
            return "暂无会话。可用 /session_new 新建。"
        active = self._sessions.active_session(chat_id)
        lines = []
        for item in sessions:
            sid = str(item.get("id", ""))
            title = str(item.get("title", "session"))
            mark = "*" if sid == active else " "
            lines.append(f"{mark} {sid[:8]} | {title} | {item.get('last_used_at', '')}")
        return "Copilot 会话列表(*为当前):\n" + "\n".join(lines)

    def session_new_text(self, chat_id: int, title: str | None = None) -> str:
        session_id = self._sessions.create_session(chat_id, title=title or "manual-new")
        return f"已新建并切换会话: {session_id}"

    def session_use_text(self, chat_id: int, session_id_prefix: str) -> str:
        session_id = self._sessions.set_active(chat_id, session_id_prefix)
        if session_id is None:
            return f"未找到会话: {session_id_prefix}"
        return f"已切换到会话: {session_id}"

    async def _worker(self) -> None:
        while True:
            task_id = await self._queue.get()
            task = self._store.get(task_id)
            if task is None or task.state is TaskState.REJECTED:
                self._queue.task_done()
                continue
            try:
                await self._execute(task)
            finally:
                self._queue.task_done()

    async def _execute(self, task: TaskRecord) -> None:
        task.state = TaskState.RUNNING
        task.touch()
        self._store.upsert(task)
        await self._notify(NotificationEvent(EventType.STARTED, task))

        try:
            if task.command:
                if not self._settings.shell_executor_enabled:
                    raise CommandExecutionError("Shell 执行能力已禁用。")
                cancel_event = asyncio.Event()
                self._cancel_events[task.id] = cancel_event
                returncode, stdout, stderr = await run_shell(
                    self._settings.default_shell,
                    task.command,
                    timeout_seconds=self._settings.command_timeout_seconds,
                    cancel_event=cancel_event,
                )
                task.log_excerpt = summarize_command_result(returncode, stdout, stderr)
                if returncode != 0:
                    raise CommandExecutionError(task.log_excerpt)
                task.result_summary = task.log_excerpt
            elif task.url:
                if not self._settings.browser_enabled:
                    raise BrowserAutomationError("浏览器能力已禁用。请将 BROWSER_ENABLED 设置为 true。")
                task.result_summary = await open_and_describe(task.url)
            else:
                raise RuntimeError("任务缺少可执行动作。")
            task.state = TaskState.COMPLETED
            task.touch()
            self._store.upsert(task)
            await self._notify(NotificationEvent(EventType.COMPLETED, task))
        except Exception as exc:
            task.state = TaskState.FAILED
            task.result_summary = str(exc)
            task.touch()
            self._store.upsert(task)
            await self._notify(NotificationEvent(EventType.FAILED, task))
        finally:
            self._cancel_events.pop(task.id, None)

    async def _notify(self, event: NotificationEvent) -> None:
        text = self._policy.render(event)
        if text:
            buttons: ButtonList | None = None
            if event.event_type is EventType.APPROVAL_REQUIRED:
                buttons = [
                    ("✅ 批准", f"approve:{event.task.id}"),
                    ("❌ 拒绝", f"deny:{event.task.id}"),
                ]
            elif event.event_type is EventType.STARTED:
                buttons = [("⛔ 打断", f"interrupt:{event.task.id}")]

            await self._send_message(event.task.chat_id, text, buttons)
            if event.event_type in {EventType.APPROVAL_REQUIRED, EventType.COMPLETED, EventType.FAILED, EventType.REJECTED}:
                self._conversation.append_turn(event.task.chat_id, "assistant", text)

    def _require_chat_task(self, chat_id: int, task_id: str) -> TaskRecord:
        task = self._store.get(task_id)
        if task is None or task.chat_id != chat_id:
            raise ValueError(f"找不到任务 {task_id}。")
        return task
