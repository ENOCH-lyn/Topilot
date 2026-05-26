from __future__ import annotations
"""Copilot CLI 调用与事件解析模块
"""

import json
import logging
import re
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path

import asyncio

from topilot.config import Settings
from topilot.models import ActionType, ChatTurn, PlannedAction

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
    tool_calls: dict[str, "ToolCallContext"] = field(default_factory=dict)


@dataclass(slots=True)
class ToolCallContext:
    """工具调用上下文"""

    tool_name: str
    arguments: dict[str, object]


@dataclass(slots=True)
class CopilotCliDiagnostic:
    """Copilot CLI 运行前诊断结果"""

    ready: bool
    summary: str
    model: str
    configured_command: str
    resolved_command: str
    workspace_dir: str
    workspace_exists: bool
    timeout_seconds: int
    allow_all_tools: bool
    add_workspace_dir: bool
    reasoning_effort: str | None
    issues: list[str] = field(default_factory=list)

    def render(self, available_models: list[str] | None = None) -> str:
        """渲染为适合 Telegram / doctor 展示的诊断文本"""

        lines = [
            f"后端状态: {self.summary}",
            f"配置命令: {self.configured_command or '-'}",
            f"解析命令: {self.resolved_command or '-'}",
            f"工作区: {self.workspace_dir}（{'存在' if self.workspace_exists else '不存在'}）",
            f"当前模型: {self.model}",
            (
                "调用参数: "
                f"timeout={self.timeout_seconds}s, "
                f"allow_all_tools={self.allow_all_tools}, "
                f"add_workspace_dir={self.add_workspace_dir}, "
                f"reasoning_effort={self.reasoning_effort or '-'}"
            ),
        ]
        if available_models:
            lines.append("可用模型: " + ", ".join(available_models))
        if self.issues:
            lines.append("待处理: " + "；".join(self.issues))
        return "\n".join(lines)


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

        diagnostic = self.diagnose_copilot_cli(model=model, workspace_dir=workspace_dir)
        if diagnostic.ready:
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
                    assistant_message=self._format_cli_failure_message(exc),
                )

        return PlannedAction(
            action_type=ActionType.RESPOND_ONLY,
            summary="Copilot CLI 未就绪",
            assistant_message=self.fallback_response(diagnostic),
        )

    def fallback_response(self, diagnostic: CopilotCliDiagnostic | None = None) -> str:
        """构造 Copilot CLI 不可用时的统一提示"""

        current = diagnostic or self.diagnose_copilot_cli()
        reason = current.summary
        issue_text = "；".join(current.issues) if current.issues else "请确认 copilot 已登录，且命令可在当前环境执行"
        return (
            f"当前后端状态: {reason}\n"
            f"原因: {issue_text}\n"
            "建议: 执行 topilot doctor 检查配置，确认 copilot 登录状态与 copilot.cli_command 后重试"
        )

    def llm_status_text(self, model: str | None = None) -> str:
        """返回当前 Copilot CLI 状态文本"""

        return self.diagnose_copilot_cli(model=model).summary

    def diagnose_copilot_cli(self, model: str | None = None, workspace_dir: str | None = None) -> CopilotCliDiagnostic:
        """检查 Copilot CLI 命令、工作区和关键调用参数是否可用"""

        configured = self._settings.copilot_cli_command.strip()
        resolved = self._resolve_copilot_command() if configured else ""
        effective_model = model or self._settings.copilot_cli_model
        effective_workspace = self._effective_workspace(workspace_dir)
        workspace_exists = effective_workspace.exists() and effective_workspace.is_dir()
        issues: list[str] = []

        if not configured:
            issues.append("copilot.cli_command 为空")
        elif not self._command_is_runnable(resolved):
            issues.append(f"命令未找到或不可执行: {configured}")

        if not workspace_exists:
            issues.append(f"工作区不存在: {effective_workspace.as_posix()}")

        if self._settings.copilot_cli_timeout_seconds <= 0:
            issues.append("copilot.timeout_seconds 必须大于 0")

        ready = not issues
        if ready:
            summary = f"Copilot CLI 已就绪（model={effective_model}）"
        else:
            summary = "Copilot CLI 未就绪（" + "；".join(issues[:2]) + "）"

        return CopilotCliDiagnostic(
            ready=ready,
            summary=summary,
            model=effective_model,
            configured_command=configured,
            resolved_command=resolved,
            workspace_dir=effective_workspace.as_posix(),
            workspace_exists=workspace_exists,
            timeout_seconds=self._settings.copilot_cli_timeout_seconds,
            allow_all_tools=self._settings.copilot_cli_allow_all_tools,
            add_workspace_dir=self._settings.copilot_cli_add_workspace_dir,
            reasoning_effort=self._settings.copilot_cli_reasoning_effort,
            issues=issues,
        )

    def _copilot_cli_ready(self) -> bool:
        return self.diagnose_copilot_cli().ready

    async def fetch_available_models(self) -> list[str]:
        """从 copilot --help 实时解析可用模型列表

        解析 CLI 输出中 --model <model> 对应的 choices
        获取失败时返回配置中的 COPILOT_MODELS
        """
        diagnostic = self.diagnose_copilot_cli()
        if not diagnostic.ready:
            logger.warning("跳过模型实时获取: %s", "; ".join(diagnostic.issues))
            return self._fallback_available_models()

        try:
            argv = self._build_copilot_help_argv()
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            raw, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                raise RuntimeError(f"copilot --help exited with {proc.returncode}")
            text = raw.decode(errors="replace")
            models = self._parse_available_models_from_help(text)
            if models:
                logger.info("实时获取到 %d 个可用模型", len(models))
                return models
        except Exception as exc:
            logger.warning("获取模型列表失败: %s", exc)
        return self._fallback_available_models()

    def _fallback_available_models(self) -> list[str]:
        """返回模型发现失败时的稳定回退列表"""

        # 回退到显式配置列表；若未配置列表，至少保留当前默认模型用于 /model 展示和切换确认。
        fallback_models = list(self._settings.copilot_available_models)
        if fallback_models:
            return fallback_models
        return [self._settings.copilot_cli_model]

    def _build_copilot_help_argv(self) -> list[str]:
        """构造 Copilot CLI 帮助命令，兼容 Windows PowerShell 脚本入口"""

        command = self._resolve_copilot_command()
        if command.lower().endswith(".ps1"):
            return [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                command,
                "--help",
            ]
        return [command, "--help"]

    def _parse_available_models_from_help(self, text: str) -> list[str]:
        """从 Copilot CLI 帮助文本中解析 --model choices 列表"""

        model_section = re.search(r"--model\s+<model>.*?choices:\s*(.*?)\)", text, re.DOTALL)
        if not model_section:
            return []

        seen: set[str] = set()
        models: list[str] = []
        for model in re.findall(r'"([^"]+)"', model_section.group(1)):
            if model in seen:
                continue
            seen.add(model)
            models.append(model)
        return models

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
            raise RuntimeError(
                f"Copilot CLI 超时：超过 {self._settings.copilot_cli_timeout_seconds}s 未完成，请检查网络、登录状态或调大 copilot.timeout_seconds"
            ) from exc

        out_text = "\n".join(stdout_lines).strip()
        err_text = "\n".join(stderr_lines).strip()
        if process.returncode != 0:
            logger.error("Copilot CLI 返回非零 code=%s session=%s", process.returncode, session_id)
            detail = self._shorten_single_line(err_text or out_text or "无错误输出", 200)
            raise RuntimeError(f"Copilot CLI 返回非零退出码 {process.returncode}: {detail}")
        if not out_text and err_text:
            out_text = err_text
        if not out_text:
            logger.error("Copilot CLI 返回空结果 session=%s", session_id)
            raise RuntimeError("Copilot CLI 返回空结果：stdout/stderr 均为空，请检查登录状态、命令路径和 --output-format json 支持")

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

        if item_type == "tool.execution_start":
            summary = self._summarize_tool_start(data, stream_state)
            return [StreamEvent(kind="log", text=summary, event_type=item_type)] if summary else []

        if item_type == "tool.execution_complete":
            summary = self._summarize_tool_complete(data, stream_state)
            return [StreamEvent(kind="log", text=summary, event_type=item_type)] if summary else []

        if item_type in {"session.tools_updated", "session.info", "user.message", "subagent.completed", "subagent.started"}:
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
            fallback_tool_text = self._shorten_single_line(text or self._extract_tool_result_text(data), 160)
            if fallback_tool_text:
                if "exited with error" in fallback_tool_text.lower() or "not available" in fallback_tool_text.lower():
                    return f"命令执行失败: {fallback_tool_text}"
                return f"工具事件输出: {fallback_tool_text}"

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

    def _summarize_tool_start(self, data: object, stream_state: StreamState) -> str:
        if not isinstance(data, dict):
            return ""
        tool_name = self._pick_first_string(data, ["toolName", "tool", "name"]).lower()
        tool_call_id = self._pick_first_string(data, ["toolCallId", "callId", "id"])
        arguments = self._extract_tool_arguments(data.get("arguments"))
        if tool_call_id and tool_name:
            stream_state.tool_calls[tool_call_id] = ToolCallContext(tool_name=tool_name, arguments=arguments)
        return self._format_tool_start(tool_name, arguments)

    def _summarize_tool_complete(self, data: object, stream_state: StreamState) -> str:
        if not isinstance(data, dict):
            return ""
        tool_call_id = self._pick_first_string(data, ["toolCallId", "callId", "id"])
        context = stream_state.tool_calls.pop(tool_call_id, None) if tool_call_id else None
        tool_name = context.tool_name if context else self._pick_first_string(data, ["toolName", "tool", "name"]).lower()
        arguments = context.arguments if context else self._extract_tool_arguments(data.get("arguments"))

        if tool_name in {"report_intent", "sql"}:
            return ""

        success = bool(data.get("success", True))
        if not success:
            return self._format_tool_failure(tool_name, arguments, data)
        return self._format_tool_success(tool_name, arguments, data)

    def _format_tool_start(self, tool_name: str, arguments: dict[str, object]) -> str:
        if not tool_name:
            return "调用工具"

        if tool_name in {"report_intent", "sql"}:
            return ""

        path = self._pick_first_string(
            arguments,
            ["path", "filePath", "dirPath", "workspacePath", "includePattern", "resourcePath", "url"],
        )
        command = self._pick_first_string(arguments, ["command", "input"])
        query = self._pick_first_string(arguments, ["query", "pattern", "symbol"])
        description = self._pick_first_string(arguments, ["description", "task", "intent", "prompt"])

        if tool_name in {"view", "read_file", "github-mcp-server-get_file_contents"}:
            if not path:
                return "读取内容"
            return f"读取文件：{path}" if self._looks_like_file(path) else f"读取目录：{path}"

        if tool_name == "list_powershell":
            return "列出 PowerShell 会话"

        if tool_name == "list_agents":
            return "列出后台 Agent"

        if tool_name in {"glob", "list_dir", "file_search"}:
            pattern = self._pick_first_string(arguments, ["pattern", "glob"])
            if path and pattern:
                return f"列出目录：{path}（pattern={pattern}）"
            if pattern:
                return f"列出目录（pattern={pattern}）"
            if path:
                return f"列出目录：{path}"
            return "列出目录"

        if tool_name in {"grep", "rg", "grep_search", "semantic_search", "search_subagent", "github-mcp-server-search_code"}:
            search_context = self._build_context_suffix(arguments, [("path", "path"), ("glob", "glob")])
            if query:
                return f"检索代码：{query}{search_context}"
            return f"检索代码{search_context}"

        if tool_name in {"powershell", "run_in_terminal", "create_and_run_task", "read_powershell", "write_powershell"}:
            if command:
                return f"执行命令：{self._shorten_single_line(command, 180)}"
            return "执行命令"

        if tool_name in {"create", "apply_patch", "write_file"}:
            if path:
                return f"写入文件：{path}"
            return "修改文件"

        if tool_name in {"task", "runsubagent"}:
            agent_type = self._pick_first_string(arguments, ["agent_type", "agentType"])
            suffix = f"（agent={agent_type}）" if agent_type else ""
            if description:
                return f"启动子任务{suffix}：{self._shorten_single_line(description, 120)}"
            return f"启动子任务{suffix}"

        if tool_name in {"web_fetch", "github-mcp-server-get_commit", "github-mcp-server-actions_get"} and path:
            return f"读取资源：{path}"
        if tool_name in {"web_fetch"}:
            url = self._pick_first_string(arguments, ["url"])
            return f"抓取网页：{url}" if url else "抓取网页"

        if tool_name == "fetch_copilot_cli_documentation":
            return "获取 Copilot CLI 文档"

        if tool_name in {"ask_user"}:
            return "向用户提问"

        if self._tool_name_has_any(tool_name, {"powershell", "terminal", "exec", "run"}):
            if command:
                return f"执行命令：{self._shorten_single_line(command, 180)}"
            return "执行命令"
        if self._tool_name_has_any(tool_name, {"search", "grep", "find"}):
            return f"检索代码：{query}" if query else "检索代码"
        if self._tool_name_has_any(tool_name, {"list", "ls"}):
            if path:
                return f"列表操作：{path}"
            return "列表操作"
        if self._tool_name_has_any(tool_name, {"read", "view", "get"}):
            if path:
                return f"读取资源：{path}"
            return "读取资源"

        return f"调用工具：{tool_name}"

    def _format_tool_success(self, tool_name: str, arguments: dict[str, object], data: dict[str, object]) -> str:
        result_text = self._extract_tool_result_text(data)
        cleaned = self._strip_process_footer(result_text)
        lowered = cleaned.lower()

        if "intent logged" in lowered:
            return ""

        if tool_name in {"view", "read_file", "github-mcp-server-get_file_contents", "create", "apply_patch", "write_file", "stop_powershell"}:
            return ""

        if tool_name == "list_powershell":
            title = "PowerShell 会话列表"
            return self._summarize_list_result(cleaned, title=title)

        if tool_name == "list_agents":
            title = "后台 Agent 列表"
            return self._summarize_list_result(cleaned, title=title)

        if tool_name in {"glob", "list_dir", "file_search"}:
            title = "目录列表" + self._build_context_suffix(arguments, [("path", "path"), ("pattern", "pattern"), ("glob", "glob")])
            return self._summarize_list_result(cleaned, title=title)

        if tool_name in {"grep", "rg", "grep_search", "semantic_search", "search_subagent", "github-mcp-server-search_code"}:
            title = "代码检索结果" + self._build_context_suffix(
                arguments,
                [("query", "query"), ("pattern", "pattern"), ("symbol", "symbol"), ("path", "path"), ("glob", "glob")],
            )
            return self._summarize_list_result(cleaned, title=title, max_items=6, line_limit=120)

        if tool_name in {"powershell", "run_in_terminal", "create_and_run_task", "read_powershell", "write_powershell"}:
            command = self._pick_first_string(arguments, ["command", "input"])
            return self._format_command_output(command, cleaned)

        if tool_name in {"ask_user"}:
            return ""

        if tool_name == "fetch_copilot_cli_documentation":
            return "文档已获取：Copilot CLI 文档（README + 帮助）"

        if tool_name == "web_fetch":
            url_suffix = self._build_context_suffix(arguments, [("url", "url")])
            if not cleaned:
                return f"网页抓取完成{url_suffix}"
            return f"网页抓取结果{url_suffix}\n{self._shorten_multiline(cleaned, 1200)}"

        if tool_name in {"task", "runsubagent"}:
            return self._format_task_result(arguments, cleaned)

        if self._tool_name_has_any(tool_name, {"powershell", "terminal", "exec", "run"}):
            command = self._pick_first_string(arguments, ["command", "input"])
            return self._format_command_output(command, cleaned)
        if self._tool_name_has_any(tool_name, {"search", "grep", "find"}):
            title = "代码检索结果" + self._build_context_suffix(
                arguments,
                [("query", "query"), ("pattern", "pattern"), ("symbol", "symbol"), ("path", "path"), ("glob", "glob")],
            )
            return self._summarize_list_result(cleaned, title=title, max_items=6, line_limit=120)
        if self._tool_name_has_any(tool_name, {"list", "ls"}):
            title = "列表结果" + self._build_context_suffix(arguments, [("path", "path"), ("pattern", "pattern"), ("glob", "glob")])
            return self._summarize_list_result(cleaned, title=title)
        if self._tool_name_has_any(tool_name, {"read", "view", "get"}):
            return ""

        if not cleaned:
            return ""
        if tool_name:
            return f"{tool_name} 返回结果：{self._shorten_single_line(cleaned, 220)}"
        return f"调用结果：{self._shorten_single_line(cleaned, 220)}"

    def _format_tool_failure(self, tool_name: str, arguments: dict[str, object], data: dict[str, object]) -> str:
        error = data.get("error")
        error_text = self._pick_first_string(error, ["message", "code"]) if isinstance(error, dict) else ""
        result_text = self._strip_process_footer(self._extract_tool_result_text(data))
        detail = error_text or result_text or "未知错误"

        if tool_name in {"powershell", "run_in_terminal", "create_and_run_task", "read_powershell", "write_powershell"}:
            command = self._pick_first_string(arguments, ["command", "input"])
            if command:
                return f"命令执行失败（command={self._shorten_single_line(command, 100)}）\n{self._shorten_multiline(detail, 1200)}"
            return f"命令执行失败\n{self._shorten_multiline(detail, 1200)}"

        if tool_name in {"view", "read_file", "github-mcp-server-get_file_contents"}:
            path = self._pick_first_string(arguments, ["path", "filePath", "resourcePath"])
            if path:
                return f"读取失败：{path}\n{self._shorten_single_line(detail, 220)}"
            return f"读取失败：{self._shorten_single_line(detail, 220)}"

        name = tool_name or "tool"
        return f"{name} 失败：{self._shorten_single_line(detail, 220)}"

    def _summarize_list_result(self, raw_text: str, title: str, max_items: int = 8, line_limit: int = 90) -> str:
        lines = self._parse_result_lines(raw_text)
        if not lines:
            return f"{title}：空"

        first_line = lines[0]
        if first_line.lower().startswith("output too large to read at once"):
            temp_path = ""
            match = re.search(r"Saved to:\s*(.+)$", first_line, re.IGNORECASE)
            if match:
                temp_path = match.group(1).strip()
            preview = [self._shorten_single_line(line, line_limit) for line in lines[1:4]]
            body_lines = []
            if temp_path:
                body_lines.append(f"• 输出过大，已保存：{temp_path}")
            else:
                body_lines.append("• 输出过大，已保存到临时文件")
            body_lines.extend(f"• {line}" for line in preview if line)
            return f"{title}\n" + "\n".join(body_lines)

        lowered = lines[0].lower()
        if lowered.startswith("no files matched"):
            return f"{title}：无匹配项"

        shown = [self._shorten_single_line(line, line_limit) for line in lines[:max_items]]
        omitted = len(lines) - len(shown)
        body = "\n".join(f"• {line}" for line in shown)
        if omitted > 0:
            body += f"\n…其余 {omitted} 条已省略"
        return f"{title} | 共 {len(lines)} 条\n{body}"

    def _format_command_output(self, command: str, output: str) -> str:
        normalized = output.replace("\r\n", "\n").replace("\r", "\n").strip()
        command_label = self._shorten_single_line(command, 120) if command else ""
        header = f"命令输出（command={command_label}）" if command_label else "命令输出"
        if not normalized:
            return f"{header}：无输出"

        condensed = self._shorten_multiline(normalized, 1800)
        return f"{header}\n{condensed}"

    def _format_task_result(self, arguments: dict[str, object], result_text: str) -> str:
        agent_type = self._pick_first_string(arguments, ["agent_type", "agentType"])
        description = self._pick_first_string(arguments, ["description", "task", "prompt"])
        suffix = self._build_context_suffix(
            {"agent": agent_type, "description": description},
            [("agent", "agent"), ("description", "description")],
        )
        title = "子任务结果" + suffix
        if not result_text:
            return f"{title}：空"
        return f"{title}\n{self._shorten_multiline(result_text, 1400)}"

    def _shorten_multiline(self, text: str, limit: int) -> str:
        normalized = text.strip()
        if len(normalized) <= limit:
            return normalized
        head = max(int(limit * 0.7), 1)
        tail = max(limit - head - 40, 1)
        omitted = len(normalized) - head - tail
        return f"{normalized[:head].rstrip()}\n...(中间省略 {omitted} 字符)...\n{normalized[-tail:].lstrip()}"

    def _parse_result_lines(self, raw_text: str) -> list[str]:
        normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.strip() for line in normalized.split("\n") if line.strip()]
        return [line for line in lines if not line.startswith("<exited with")]

    def _strip_process_footer(self, text: str) -> str:
        if not text:
            return ""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line for line in normalized.split("\n") if line.strip()]
        while lines and lines[-1].strip().startswith("<exited with"):
            lines.pop()
        return "\n".join(lines).strip()

    def _extract_tool_arguments(self, value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed = json.loads(stripped)
                except JSONDecodeError:
                    return {}
                return parsed if isinstance(parsed, dict) else {}
        return {}

    def _build_context_suffix(self, arguments: dict[str, object], fields: list[tuple[str, str]]) -> str:
        pairs: list[str] = []
        for key, label in fields:
            value = self._pick_first_string(arguments, [key])
            if not value:
                continue
            pairs.append(f"{label}={self._shorten_single_line(value, 80)}")
        if not pairs:
            return ""
        return "（" + ", ".join(pairs) + "）"

    def _tool_name_has_any(self, tool_name: str, tokens: set[str]) -> bool:
        return any(token in tool_name for token in tokens)

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
        keys = {"toolName", "tool", "toolCallId", "success", "result", "toolTelemetry", "arguments", "error"}
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
            return Path(resolved).as_posix()
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

    def _command_is_runnable(self, command: str) -> bool:
        """判断解析后的命令是否能在当前系统中启动"""

        if not command:
            return False
        if shutil.which(command):
            return True
        if "/" in command or "\\" in command or Path(command).is_absolute():
            return Path(command).expanduser().exists()
        return False

    def _effective_workspace(self, workspace_dir: str | None = None) -> Path:
        """返回本次调用实际会使用的工作区目录"""

        if workspace_dir:
            candidate = Path(workspace_dir).expanduser()
            if candidate.exists() and candidate.is_dir():
                return candidate.resolve()
        return self._settings.workspace_root

    def _format_cli_failure_message(self, exc: Exception) -> str:
        """把 CLI 运行时异常压缩成稳定、可行动的用户提示"""

        detail = self._shorten_single_line(str(exc) or exc.__class__.__name__, 200)
        return (
            "Copilot CLI 当前调用失败\n"
            f"错误: {detail}\n"
            "建议: 执行 topilot doctor 检查命令、登录状态、网络代理和模型配置后重试"
        )

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
