from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    telegram_bot_token: str
    allowed_chat_ids: set[int]
    workspace_root: Path
    task_db_path: Path
    chat_db_path: Path
    session_db_path: Path
    telegram_proxy_url: str | None
    copilot_cli_enabled: bool
    copilot_cli_command: str
    copilot_cli_model: str
    copilot_cli_timeout_seconds: int
    copilot_cli_allow_all_tools: bool
    copilot_cli_add_workspace_dir: bool
    copilot_cli_reasoning_effort: str
    copilot_cli_history_turns: int
    copilot_cli_forward_reasoning: bool
    copilot_cli_reasoning_max_chars: int
    default_shell: str
    shell_executor_enabled: bool
    browser_enabled: bool
    approval_required_for_shell: bool
    command_timeout_seconds: int


class ConfigurationError(RuntimeError):
    pass


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_chat_ids(value: str | None) -> set[int]:
    if not value:
        return set()
    result: set[int] = set()
    for item in value.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        result.add(int(stripped))
    return result


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigurationError("Missing TELEGRAM_BOT_TOKEN.")

    workspace_root = Path(os.getenv("WORKSPACE_ROOT", Path.cwd().as_posix())).resolve()
    task_db_path = Path(os.getenv("TASK_DB_PATH", workspace_root / "data" / "tasks.json")).resolve()
    chat_db_path = Path(os.getenv("CHAT_DB_PATH", workspace_root / "data" / "chats.json")).resolve()
    session_db_path = Path(os.getenv("SESSION_DB_PATH", workspace_root / "data" / "sessions.json")).resolve()
    task_db_path.parent.mkdir(parents=True, exist_ok=True)
    chat_db_path.parent.mkdir(parents=True, exist_ok=True)
    session_db_path.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        telegram_bot_token=token,
        allowed_chat_ids=_parse_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS")),
        workspace_root=workspace_root,
        task_db_path=task_db_path,
        chat_db_path=chat_db_path,
        session_db_path=session_db_path,
        telegram_proxy_url=os.getenv("TELEGRAM_PROXY_URL", "").strip() or None,
        copilot_cli_enabled=_parse_bool(os.getenv("COPILOT_CLI_ENABLED"), True),
        copilot_cli_command=os.getenv("COPILOT_CLI_COMMAND", "copilot").strip() or "copilot",
        copilot_cli_model=os.getenv("COPILOT_CLI_MODEL", "gpt-5.3-codex").strip() or "gpt-5.3-codex",
        copilot_cli_timeout_seconds=int(os.getenv("COPILOT_CLI_TIMEOUT_SECONDS", "120")),
        copilot_cli_allow_all_tools=_parse_bool(os.getenv("COPILOT_CLI_ALLOW_ALL_TOOLS"), True),
        copilot_cli_add_workspace_dir=_parse_bool(os.getenv("COPILOT_CLI_ADD_WORKSPACE_DIR"), True),
        copilot_cli_reasoning_effort=os.getenv("COPILOT_CLI_REASONING_EFFORT", "medium").strip() or "medium",
        copilot_cli_history_turns=int(os.getenv("COPILOT_CLI_HISTORY_TURNS", "20")),
        copilot_cli_forward_reasoning=_parse_bool(os.getenv("COPILOT_CLI_FORWARD_REASONING"), True),
        copilot_cli_reasoning_max_chars=int(os.getenv("COPILOT_CLI_REASONING_MAX_CHARS", "0")),
        default_shell=os.getenv("DEFAULT_SHELL", "powershell").strip() or "powershell",
        shell_executor_enabled=_parse_bool(os.getenv("SHELL_EXECUTOR_ENABLED"), True),
        browser_enabled=_parse_bool(os.getenv("BROWSER_ENABLED"), False),
        approval_required_for_shell=_parse_bool(os.getenv("APPROVAL_REQUIRED_FOR_SHELL"), True),
        command_timeout_seconds=int(os.getenv("COMMAND_TIMEOUT_SECONDS", "120")),
    )
