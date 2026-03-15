from __future__ import annotations
"""Copilot CLI 调用与事件解析模块
"""

import json
import logging
import re
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path

import asyncio

from copilot_in_telegram.config import Settings
from copilot_in_telegram.models import ActionType, ChatTurn, PlannedAction

URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)

ProgressLogger = Callable[[str], Awaitable[None]]
ReplyStreamer = Callable[[str], Awaitable[None]]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StreamEvent:
    """流式事件统一结构"""

    kind: str
    text: str
    event_type: str


@dataclass(slots=True)
class StreamState:
    """单次流式输出解析状态"""

    has_reply_delta_in_turn: bool = False


class AssistantPlanner:
    """将用户输入转换为 Copilot CLI 可执行计划"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def plan(
        self,
        session_id: str,
        history: list[ChatTurn],
        instruction: str,
        model: str | None = None,
        workspace_dir: str | None = None,
        progress_logger: ProgressLogger | None = None,
        reply_streamer: ReplyStreamer | None = None,
    ) -> PlannedAction:
        """执行一次 Copilot 规划流程"""

        if self._copilot_cli_ready():
            try:
                return await self._plan_with_copilot_cli(
                    session_id,
                    history,
                    instruction,
                    model=model,
                    workspace_dir=workspace_dir,
                    progress_logger=progress_logger,
                    reply_streamer=reply_streamer,
                )
            except Exception as exc:
                return PlannedAction(
                    action_type=ActionType.RESPOND_ONLY,
                    summary="Copilot CLI 调用失败",
                    assistant_message=(
                        "Copilot CLI 当前调用失败\n"
                        f"错误: {str(exc)[:200]}\n"
                        "请检查 copilot 登录状态与命令配置，然后重试"
                    ),
                )

        return PlannedAction(
            action_type=ActionType.RESPOND_ONLY,
            summary="Copilot CLI 未就绪",
            assistant_message=self.fallback_response(),
        )

    def fallback_response(self) -> str:
        """构造 Copilot CLI 不可用时的统一提示"""

        reason = self.llm_status_text()
        return (
            f"当前后端状态: {reason}\n"
            "Copilot CLI 当前不可用，请确认 copilot 已登录，配置项 copilot.cli_command 正确"
        )

    def llm_status_text(self, model: str | None = None) -> str:
        """返回当前 Copilot CLI 状态文本"""

        if self._copilot_cli_ready():
            effective = model or self._settings.copilot_cli_model
            return f"Copilot CLI 已启用（model={effective}）"

        copilot_reasons: list[str] = []
        if not self._settings.copilot_cli_command:
            copilot_reasons.append("copilot.cli_command 为空")

        if copilot_reasons:
            return "Copilot 未启用(" + "; ".join(copilot_reasons) + ")"
        return "Copilot CLI 未就绪"

    def _copilot_cli_ready(self) -> bool:
        return bool(self._settings.copilot_cli_command)

    async def fetch_available_models(self) -> list[str]:
        """从 copilot --help 实时解析可用模型列表

        解析 CLI 输出中 --model <model> 对应的 choices
        获取失败时返回配置中的 COPILOT_MODELS
        """
        try:
            command = self._resolve_copilot_command()
            proc = await asyncio.create_subprocess_exec(
                command, "--help",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            raw, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            text = raw.decode(errors="replace")
            # 匹配 --model 说明段中的 choices 列表
            m = re.search(r"--model\s+<model>.*?choices:\s*(.*?)\)", text, re.DOTALL)
            if m:
                models = re.findall(r'"([^"]+)"', m.group(1))
                if models:
                    logger.info("实时获取到 %d 个可用模型", len(models))
                    return models
        except Exception as exc:
            logger.warning("获取模型列表失败: %s", exc)
        # 回退到显式配置列表
        return list(self._settings.copilot_available_models)

    async def _plan_with_copilot_cli(
        self,
        session_id: str,
        history: list[ChatTurn],
        instruction: str,
        model: str | None = None,
        workspace_dir: str | None = None,
        progress_logger: ProgressLogger | None = None,
        reply_streamer: ReplyStreamer | None = None,
    ) -> PlannedAction:
        """调用 Copilot CLI 并实时消费 JSONL 输出"""

        prompt = self._build_copilot_prompt(history, instruction)
        effective_model = model or self._settings.copilot_cli_model
        argv = self._build_copilot_argv(prompt, session_id, model=effective_model, workspace_dir=workspace_dir)
        if self._settings.copilot_cli_allow_all_tools:
            argv.append("--allow-all-tools")

        effective_cwd = self._settings.workspace_root
        if workspace_dir:
            candidate = Path(workspace_dir)
            if candidate.exists() and candidate.is_dir():
                effective_cwd = candidate

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=effective_cwd.as_posix(),
        )
        logger.info("Copilot CLI 启动 session=%s model=%s cwd=%s", session_id, effective_model, effective_cwd)
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        stream_state = StreamState()

        async def consume_stdout() -> None:
            assert process.stdout is not None
            while True:
                raw_line = await process.stdout.readline()
                if not raw_line:
                    break
                line = raw_line.decode(errors="replace").rstrip("\r\n")
                stdout_lines.append(line)
                await self._forward_stdout_line(line, progress_logger, reply_streamer, stream_state)

        async def consume_stderr() -> None:
            assert process.stderr is not None
            while True:
                raw_line = await process.stderr.readline()
                if not raw_line:
                    break
                line = raw_line.decode(errors="replace").rstrip("\r\n")
                stderr_lines.append(line)
                if progress_logger and line.strip():
                    await progress_logger(f"[stderr] {line.strip()}")

        try:
            await asyncio.wait_for(
                asyncio.gather(consume_stdout(), consume_stderr(), process.wait()),
                timeout=self._settings.copilot_cli_timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            logger.error("Copilot CLI 超时 session=%s timeout=%ss", session_id, self._settings.copilot_cli_timeout_seconds)
            raise RuntimeError("Copilot CLI 超时") from exc

        out_text = "\n".join(stdout_lines).strip()
        err_text = "\n".join(stderr_lines).strip()
        if process.returncode != 0:
            logger.error("Copilot CLI 返回非零 code=%s session=%s", process.returncode, session_id)
            raise RuntimeError(err_text or out_text or f"Copilot CLI exited with {process.returncode}")
        if not out_text and err_text:
            out_text = err_text
        if not out_text:
            logger.error("Copilot CLI 返回空结果 session=%s", session_id)
            raise RuntimeError("Copilot CLI 返回空结果")

        logger.info("Copilot CLI 调用完成 session=%s", session_id)

        return self._parse_copilot_response(out_text)

    async def _forward_stdout_line(
        self,
        line: str,
        progress_logger: ProgressLogger | None,
        reply_streamer: ReplyStreamer | None,
        stream_state: StreamState,
    ) -> None:
        """解析单行 JSON 并分发为日志/回复事件"""

        stripped = line.strip()
        if not stripped:
            return
        if not stripped.startswith("{"):
            return
        try:
            item = json.loads(stripped)
        except JSONDecodeError:
            return

        for event in self._stream_events_from_item(item, stream_state):
            if event.kind == "reply" and reply_streamer:
                await reply_streamer(event.text)
            elif event.kind == "log" and progress_logger:
                await progress_logger(event.text)

    def _build_copilot_prompt(self, history: list[ChatTurn], instruction: str) -> str:
        """构造发送给 Copilot CLI 的 prompt"""

        return instruction.strip()

    def _parse_copilot_response(self, raw_content: str) -> PlannedAction:
        """从 CLI 原始输出中提取最终回复"""

        final_reply, reasoning = self._extract_copilot_jsonl_parts(raw_content)
        text = (final_reply or raw_content).strip()
        if not text:
            text = "Copilot 返回内容为空，请检查配置"
        if len(text) > 4000:
            text = text[:4000] + "..."
        return PlannedAction(
            action_type=ActionType.RESPOND_ONLY,
            summary="Copilot 对话回复",
            assistant_message=text,
            reasoning_message=reasoning,
        )

    def _stream_events_from_item(self, item: dict[str, object], stream_state: StreamState) -> list[StreamEvent]:
        item_type = str(item.get("type", "")).strip() or "unknown"
        data = item.get("data")

        if item_type == "assistant.turn_start":
            stream_state.has_reply_delta_in_turn = False
            return []

        if item_type == "assistant.turn_end":
            stream_state.has_reply_delta_in_turn = False
            return []

        if item_type in {"session.tools_updated", "user.message", "subagent.completed", "subagent.started"}:
            return []

        if isinstance(data, dict) and self._is_noisy_payload(data):
            return []

        if item_type == "assistant.reasoning_delta":
            return []

        content = data.get("content") if isinstance(data, dict) else data
        text_parts = self._extract_text_parts(content)
        text = "\n".join(part for part in text_parts if part).strip()

        delta_text = self._extract_delta_text(data)
        if item_type == "assistant.message_delta":
            if not delta_text:
                return []
            stream_state.has_reply_delta_in_turn = True
            return [StreamEvent(kind="reply", text=delta_text, event_type=item_type)]

        if delta_text:
            return []

        if item_type == "assistant.message":
            if stream_state.has_reply_delta_in_turn:
                return []
            return [StreamEvent(kind="reply", text=text, event_type=item_type)] if text else []

        if item_type == "assistant.reasoning":
            concise = self._compact_reasoning(text)
            return [StreamEvent(kind="log", text=f"思考: {concise}", event_type=item_type)] if concise else []

        summary = self._summarize_stream_item(item_type, data, text)
        if not summary:
            return []
        return [StreamEvent(kind="log", text=summary, event_type=item_type)]

    def _summarize_stream_item(self, item_type: str, data: object, text: str) -> str:
        if item_type.startswith("tool") or self._looks_like_tool_payload(data):
            tool_line = self._summarize_tool_line(data)
            if tool_line:
                return tool_line
            fallback_tool_text = self._shorten_single_line(text or self._extract_tool_result_text(data), 160)
            if fallback_tool_text:
                if "exited with error" in fallback_tool_text.lower() or "not available" in fallback_tool_text.lower():
                    return f"命令执行失败: {fallback_tool_text}"
                return f"工具结果: {fallback_tool_text}"

        headline = self._pick_first_string(data, ["title", "label", "name", "toolName", "tool", "command", "path", "url"])
        detail = self._pick_first_string(
            data,
            ["message", "summary", "description", "status", "result", "detail", "value"],
        )
        detail = detail or text

        prefix = self._event_prefix(item_type)
        if headline and detail and detail != headline:
            rendered = f"{prefix} {headline}\n{detail}"
        elif headline:
            rendered = f"{prefix} {headline}"
        elif detail:
            rendered = f"{prefix} {detail}"
        else:
            return ""

        return rendered[:800] + ("..." if len(rendered) > 800 else "")

    def _summarize_tool_line(self, data: object) -> str:
        tool_name = self._pick_first_string(data, ["toolName", "tool", "name"]).lower()
        if not tool_name:
            return ""

        if tool_name in {"report_intent", "sql"}:
            return ""

        path = self._pick_first_string(
            data,
            ["path", "filePath", "dirPath", "workspacePath", "includePattern", "resourcePath", "url"],
        )
        query = self._pick_first_string(data, ["query", "symbol", "command", "taskId"])
        result_text = self._extract_tool_result_text(data)
        if result_text and "PowerShell 6+ (pwsh) is not available" in result_text:
            return "命令执行失败: 当前环境缺少 pwsh（PowerShell 7）"

        if tool_name in {"view", "read_file"}:
            if not path:
                return "读取内容"
            return f"读取文件: {path}" if self._looks_like_file(path) else f"扫描目录: {path}"
        if tool_name in {"list_dir", "file_search"}:
            return f"扫描目录: {path}" if path else "扫描目录"
        if tool_name in {"grep_search", "semantic_search", "search_subagent"}:
            return f"检索: {query}" if query else "检索代码"
        if tool_name in {"run_in_terminal", "create_and_run_task"}:
            if query:
                return f"执行命令: {query}"
            if result_text:
                return self._shorten_single_line(result_text, 140)
            return "执行命令"
        if tool_name in {"apply_patch"}:
            return "修改代码"
        if tool_name in {"get_errors"}:
            return "检查错误"
        if tool_name in {"runsubagent"}:
            return "启动子任务"

        return f"调用工具: {tool_name}"

    def _is_noisy_payload(self, data: dict[str, object]) -> bool:
        tool_name = self._pick_first_string(data, ["toolName", "tool", "name"]).lower()
        if tool_name in {"report_intent", "sql"}:
            return True
        message = self._pick_first_string(data, ["message", "summary", "description"]).lower()
        if "intent logged" in message:
            return True
        return False

    def _looks_like_tool_payload(self, data: object) -> bool:
        if not isinstance(data, dict):
            return False
        keys = {"toolName", "tool", "toolCallId", "success", "result", "toolTelemetry"}
        return any(key in data for key in keys)

    def _extract_tool_result_text(self, data: object) -> str:
        if not isinstance(data, dict):
            return ""
        result = data.get("result")
        if isinstance(result, dict):
            preferred = self._pick_first_string(result, ["content", "detailedContent", "message", "summary"])
            if preferred:
                return preferred
        return self._pick_first_string(data, ["message", "summary", "description"])

    def _looks_like_file(self, path: str) -> bool:
        name = Path(path).name
        return "." in name and not name.startswith(".")

    def _compact_reasoning(self, text: str) -> str:
        trimmed = text.strip()
        if not trimmed:
            return ""
        trimmed = re.sub(r"\*+", "", trimmed)
        return self._shorten_single_line(trimmed, 120)

    def _shorten_single_line(self, text: str, limit: int) -> str:
        single = " ".join(text.split())
        if len(single) <= limit:
            return single
        return single[:limit] + "..."

    def _event_prefix(self, item_type: str) -> str:
        if item_type.startswith("tool"):
            return "[工具]"
        if item_type.startswith("assistant"):
            return "[助手]"
        if item_type.startswith("planner") or item_type.startswith("task"):
            return "[步骤]"
        if item_type.startswith("error"):
            return "[错误]"
        return f"[{item_type}]"

    def _pick_first_string(self, data: object, keys: list[str]) -> str:
        if not isinstance(data, dict):
            return ""
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in data.values():
            if isinstance(value, dict):
                nested = self._pick_first_string(value, keys)
                if nested:
                    return nested
        return ""

    def _compact_json(self, data: object) -> str:
        if data is None:
            return ""
        try:
            return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        except TypeError:
            return str(data)

    def _extract_delta_text(self, data: object) -> str:
        if not isinstance(data, dict):
            return ""
        delta_keys = ("deltaContent", "delta", "textDelta", "chunk")
        for key in delta_keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        content = data.get("content")
        if isinstance(content, dict):
            for key in delta_keys:
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def _build_copilot_argv(
        self,
        prompt: str,
        session_id: str,
        model: str | None = None,
        workspace_dir: str | None = None,
    ) -> list[str]:
        command = self._resolve_copilot_command()
        effective_model = model or self._settings.copilot_cli_model
        safe_prompt = self._normalize_prompt_for_command(prompt, command)
        base_args = [
            "--resume",
            session_id,
            "--model",
            effective_model,
            "--output-format",
            "json",
            "-p",
            safe_prompt,
            "-s",
        ]
        if self._settings.copilot_cli_reasoning_effort:
            base_args.extend(["--reasoning-effort", self._settings.copilot_cli_reasoning_effort])
        if self._settings.copilot_cli_add_workspace_dir:
            add_dir = workspace_dir or self._settings.workspace_root.as_posix()
            base_args.extend(["--add-dir", add_dir])
        if command.lower().endswith(".ps1"):
            return [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                command,
                *base_args,
            ]
        return [command, *base_args]

    def _resolve_copilot_command(self) -> str:
        configured = self._settings.copilot_cli_command.strip()
        resolved = shutil.which(configured) if configured else None
        if resolved:
            return resolved
        if configured and ("/" in configured or "\\" in configured):
            return configured

        discovered = shutil.which("copilot")
        if discovered:
            return discovered

        bat_candidate = (
            Path.home()
            / "AppData"
            / "Roaming"
            / "Code"
            / "User"
            / "globalStorage"
            / "github.copilot-chat"
            / "copilotCli"
            / "copilot.bat"
        )
        if bat_candidate.exists():
            return bat_candidate.as_posix()

        fallback_ps1 = (
            Path.home()
            / "AppData"
            / "Roaming"
            / "Code"
            / "User"
            / "globalStorage"
            / "github.copilot-chat"
            / "copilotCli"
            / "copilot.ps1"
        )
        if fallback_ps1.exists():
            return fallback_ps1.as_posix()
        return configured or "copilot"

    def _normalize_prompt_for_command(self, prompt: str, command: str) -> str:
        """根据命令类型规范化 prompt

        - bat/cmd: 将真实换行转成字面 \n，避免 Windows cmd 参数截断
        - 其他类型: 保持原样
        """

        suffix = Path(command).suffix.lower()
        if suffix in {".bat", ".cmd"}:
            normalized = prompt.replace("\r\n", "\n").replace("\r", "\n")
            return normalized.replace("\n", r"\n")
        return prompt

    def _extract_copilot_jsonl_parts(self, raw_content: str) -> tuple[str, str]:
        latest_message = ""
        latest_reasoning = ""
        for line in raw_content.splitlines():
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            try:
                item = json.loads(stripped)
            except JSONDecodeError:
                continue
            data = item.get("data")
            content = data.get("content") if isinstance(data, dict) else data
            content_parts = self._extract_text_parts(content)
            if item.get("type") == "assistant.reasoning":
                reasoning_text = "\n".join(content_parts).strip()
                if reasoning_text:
                    latest_reasoning = reasoning_text
            if item.get("type") == "assistant.message":
                message_text = "\n".join(content_parts).strip()
                if message_text:
                    latest_message = message_text
        return latest_message, latest_reasoning

    def _extract_text_parts(self, content: object) -> list[str]:
        if isinstance(content, str):
            text = content.strip()
            return [text] if text else []

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                parts.extend(self._extract_text_parts(item))
            return parts

        if isinstance(content, dict):
            parts: list[str] = []
            preferred_keys = ("text", "content", "value", "message")
            handled_keys: set[str] = set()
            for key in preferred_keys:
                if key in content:
                    handled_keys.add(key)
                    parts.extend(self._extract_text_parts(content[key]))
            for key, value in content.items():
                if key in handled_keys:
                    continue
                if isinstance(value, (list, dict)):
                    parts.extend(self._extract_text_parts(value))
            return parts

        return []
