from __future__ import annotations

import json
import re
import shutil
from json import JSONDecodeError
from pathlib import Path

import asyncio

from copilot_in_telegram.config import Settings
from copilot_in_telegram.models import ActionType, ChatTurn, PlannedAction

URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


class AssistantPlanner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def plan(self, session_id: str, history: list[ChatTurn], instruction: str) -> PlannedAction:
        if self._copilot_cli_ready():
            try:
                return await self._plan_with_copilot_cli(session_id, history, instruction)
            except Exception as exc:
                return PlannedAction(
                    action_type=ActionType.RESPOND_ONLY,
                    summary="Copilot CLI 调用失败，回退到本地规则",
                    assistant_message=(
                        "Copilot CLI 当前调用失败，已回退到本地规则模式。\n"
                        f"错误: {str(exc)[:200]}\n"
                        "先在终端执行 `copilot login`，然后用 /llm 检查状态。"
                    ),
                    requires_approval=False,
                )

        return PlannedAction(
            action_type=ActionType.RESPOND_ONLY,
            summary="未启用 Copilot CLI，使用本地规则",
            assistant_message=self.fallback_response(),
            requires_approval=False,
        )

    def fallback_response(self) -> str:
        reason = self.llm_status_text()
        return (
            "我现在会把 Telegram 消息转给 Copilot CLI。\n"
            f"当前后端状态: {reason}\n"
            "如果你看到这个提示，说明 Copilot CLI 当前不可用，请先在本机终端执行 `copilot login`。"
        )

    def llm_status_text(self) -> str:
        if self._copilot_cli_ready():
            return f"Copilot CLI 已启用（model={self._settings.copilot_cli_model}）"

        copilot_reasons: list[str] = []
        if not self._settings.copilot_cli_enabled:
            copilot_reasons.append("COPILOT_CLI_ENABLED=false")
        if not self._settings.copilot_cli_command:
            copilot_reasons.append("COPILOT_CLI_COMMAND 为空")

        if copilot_reasons:
            return "Copilot 未启用(" + "; ".join(copilot_reasons) + ")"
        return "Copilot CLI 未就绪"

    def _copilot_cli_ready(self) -> bool:
        return bool(self._settings.copilot_cli_enabled and self._settings.copilot_cli_command)

    async def _plan_with_copilot_cli(self, session_id: str, history: list[ChatTurn], instruction: str) -> PlannedAction:
        prompt = self._build_copilot_prompt(history, instruction)
        argv = self._build_copilot_argv(prompt, session_id)
        if self._settings.copilot_cli_allow_all_tools:
            argv.append("--allow-all-tools")

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._settings.copilot_cli_timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            raise RuntimeError("Copilot CLI 超时。") from exc

        out_text = stdout.decode(errors="replace").strip()
        err_text = stderr.decode(errors="replace").strip()
        if process.returncode != 0:
            raise RuntimeError(err_text or out_text or f"Copilot CLI exited with {process.returncode}")
        if not out_text and err_text:
            out_text = err_text
        if not out_text:
            raise RuntimeError("Copilot CLI 返回空结果。")

        return self._parse_copilot_response(out_text)

    def _build_copilot_prompt(self, history: list[ChatTurn], instruction: str) -> str:
        return instruction.strip()

    def _parse_copilot_response(self, raw_content: str) -> PlannedAction:
        final_reply, reasoning = self._extract_copilot_jsonl_parts(raw_content)
        text = (final_reply or raw_content).strip()
        if not text:
            text = "Copilot 返回了空内容，请重试。"
        if len(text) > 4000:
            text = text[:4000] + "..."
        reasoning_cap = self._settings.copilot_cli_reasoning_max_chars
        if reasoning_cap > 0 and len(reasoning) > reasoning_cap:
            reasoning = reasoning[:reasoning_cap] + "..."
        return PlannedAction(
            action_type=ActionType.RESPOND_ONLY,
            summary="Copilot 对话回复",
            assistant_message=text,
            reasoning_message=reasoning,
            requires_approval=False,
        )

    def _build_copilot_argv(self, prompt: str, session_id: str) -> list[str]:
        command = self._resolve_copilot_command()
        base_args = [
            "--resume",
            session_id,
            "--model",
            self._settings.copilot_cli_model,
            "--reasoning-effort",
            self._settings.copilot_cli_reasoning_effort,
            "--output-format",
            "json",
            "-p",
            prompt,
            "-s",
        ]
        if self._settings.copilot_cli_add_workspace_dir:
            base_args.extend(["--add-dir", self._settings.workspace_root.as_posix()])
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
        if configured and shutil.which(configured):
            return configured
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

    def _extract_copilot_jsonl_parts(self, raw_content: str) -> tuple[str, str]:
        message_parts: list[str] = []
        reasoning_parts: list[str] = []
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
                reasoning_parts.extend(content_parts)
            if item.get("type") == "assistant.message":
                message_parts.extend(content_parts)
        return "\n".join(message_parts).strip(), "\n".join(reasoning_parts).strip()

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
