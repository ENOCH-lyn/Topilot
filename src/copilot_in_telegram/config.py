from __future__ import annotations
"""项目配置加载模块
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

def _parse_models(value: str | None) -> list[str]:
    """解析内容为模型列表"""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(slots=True)
class Settings:
    """应用运行配置"""

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
    copilot_available_models: list[str]
    log_file_path: Path
    log_level: str
    console_log_level: str
    httpx_log_level: str
    session_watch_interval_seconds: float


class ConfigurationError(RuntimeError):
    """配置缺失或非法时抛出的异常"""

    pass


def _parse_bool(value: str | None, default: bool) -> bool:
    """将字符串环境变量解析为布尔值"""

    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_chat_ids(value: str | None) -> set[int]:
    """解析 Telegram Chat ID 列表"""

    if not value:
        return set()
    result: set[int] = set()
    for item in value.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        result.add(int(stripped))
    return result


def _parse_float(value: str | None, default: float) -> float:
    """将字符串环境变量解析为浮点数"""

    if value is None:
        return default
    try:
        return float(value.strip())
    except ValueError:
        return default


def load_settings() -> Settings:
    """加载并返回应用配置"""

    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigurationError("请配置TELEGRAM_BOT_TOKEN")

    workspace_root = Path(os.getenv("WORKSPACE_ROOT", Path.cwd().as_posix())).resolve()
    chat_db_path = Path(os.getenv("CHAT_DB_PATH", workspace_root / "data" / "chats.json")).resolve()
    session_db_path = Path(os.getenv("SESSION_DB_PATH", workspace_root / "data" / "sessions.json")).resolve()
    log_file_path = Path(os.getenv("LOG_FILE_PATH", workspace_root / "data" / "app.log")).resolve()
    chat_db_path.parent.mkdir(parents=True, exist_ok=True)
    session_db_path.parent.mkdir(parents=True, exist_ok=True)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        telegram_bot_token=token,
        allowed_chat_ids=_parse_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS")),
        workspace_root=workspace_root,
        chat_db_path=chat_db_path,
        session_db_path=session_db_path,
        telegram_proxy_url=os.getenv("TELEGRAM_PROXY_URL", "").strip() or None,
        copilot_cli_command=os.getenv("COPILOT_CLI_COMMAND", "copilot").strip() or "copilot",
        copilot_cli_model=os.getenv("COPILOT_CLI_MODEL", "gpt-4.1").strip() or "gpt-4.1",
        copilot_cli_timeout_seconds=int(os.getenv("COPILOT_CLI_TIMEOUT_SECONDS", "3600")),
        copilot_cli_allow_all_tools=_parse_bool(os.getenv("COPILOT_CLI_ALLOW_ALL_TOOLS"), True),
        copilot_cli_add_workspace_dir=_parse_bool(os.getenv("COPILOT_CLI_ADD_WORKSPACE_DIR"), True),
        copilot_cli_reasoning_effort=os.getenv("COPILOT_CLI_REASONING_EFFORT", "").strip() or None,
        copilot_cli_forward_reasoning=_parse_bool(os.getenv("COPILOT_CLI_FORWARD_REASONING"), True),
        copilot_available_models=_parse_models(os.getenv("COPILOT_MODELS")),
        log_file_path=log_file_path,
        log_level=(os.getenv("LOG_LEVEL", "INFO").strip() or "INFO").upper(),
        console_log_level=(os.getenv("CONSOLE_LOG_LEVEL", "INFO").strip() or "INFO").upper(),
        httpx_log_level=(os.getenv("HTTPX_LOG_LEVEL", "WARNING").strip() or "WARNING").upper(),
        session_watch_interval_seconds=_parse_float(os.getenv("SESSION_WATCH_INTERVAL_SECONDS"), 4.0),
    )
