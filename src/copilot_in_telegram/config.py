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
    chat_db_path: Path
    session_db_path: Path
    telegram_proxy_url: str | None
    copilot_cli_command: str
    copilot_cli_model: str
    copilot_cli_timeout_seconds: int
    copilot_cli_allow_all_tools: bool
    copilot_cli_add_workspace_dir: bool
    copilot_cli_reasoning_effort: str | None
    copilot_cli_forward_reasoning: bool


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
        raise ConfigurationError("请配置TELEGRAM_BOT_TOKEN")

    workspace_root = Path(os.getenv("WORKSPACE_ROOT", Path.cwd().as_posix())).resolve()
    chat_db_path = Path(os.getenv("CHAT_DB_PATH", workspace_root / "data" / "chats.json")).resolve()
    session_db_path = Path(os.getenv("SESSION_DB_PATH", workspace_root / "data" / "sessions.json")).resolve()
    chat_db_path.parent.mkdir(parents=True, exist_ok=True)
    session_db_path.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        telegram_bot_token=token,
        allowed_chat_ids=_parse_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS")),
        workspace_root=workspace_root,
        chat_db_path=chat_db_path,
        session_db_path=session_db_path,
        telegram_proxy_url=os.getenv("TELEGRAM_PROXY_URL", "").strip() or None,
        copilot_cli_command=os.getenv("COPILOT_CLI_COMMAND").strip() or "copilot",
        copilot_cli_model=os.getenv("COPILOT_CLI_MODEL").strip() or "gpt-4.1",
        copilot_cli_timeout_seconds=int(os.getenv("COPILOT_CLI_TIMEOUT_SECONDS", "3600")),
        copilot_cli_allow_all_tools=_parse_bool(os.getenv("COPILOT_CLI_ALLOW_ALL_TOOLS"), True),
        copilot_cli_add_workspace_dir=_parse_bool(os.getenv("COPILOT_CLI_ADD_WORKSPACE_DIR"), True),
        copilot_cli_reasoning_effort=os.getenv("COPILOT_CLI_REASONING_EFFORT", "").strip() or None,
        copilot_cli_forward_reasoning=_parse_bool(os.getenv("COPILOT_CLI_FORWARD_REASONING"), True),
    )
