from __future__ import annotations
"""项目配置加载模块"""

import json
import shutil
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

from topilot.paths import AppPaths, build_app_paths, ensure_app_dirs


def _parse_models(value: str | None) -> list[str]:
    """解析内容为模型列表"""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_models_array(value: object) -> list[str]:
    """从数组解析模型列表"""

    if isinstance(value, str):
        return _parse_models(value)
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        trimmed = item.strip()
        if trimmed:
            result.append(trimmed)
    return result


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
    app_home: Path
    config_path: Path


class ConfigurationError(RuntimeError):
    """配置缺失或非法时抛出的异常"""

    pass


@dataclass(slots=True)
class DoctorReport:
    """启动前诊断结果"""

    app_home: Path
    config_path: Path
    has_config: bool
    config_status: str
    telegram_token_status: str
    copilot_cli_command: str | None
    copilot_cli_resolved_command: str | None
    copilot_cli_runnable: bool | None
    copilot_model: str | None
    copilot_timeout_seconds: int | None
    workspace_root: str | None
    data_dir_exists: bool
    logs_dir_exists: bool
    workspace_dir_exists: bool
    runtime_workspace_exists: bool | None
    issues: list[str]


def _parse_bool(value: object, default: bool) -> bool:
    """将值解析为布尔值"""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _parse_chat_ids(value: object) -> set[int]:
    """解析 Telegram Chat ID 列表"""

    if not value:
        return set()
    result: set[int] = set()
    if isinstance(value, list):
        for item in value:
            try:
                result.add(int(item))
            except (TypeError, ValueError):
                continue
        return result
    if isinstance(value, str):
        for item in value.split(","):
            stripped = item.strip()
            if not stripped:
                continue
            try:
                result.add(int(stripped))
            except ValueError:
                continue
    return result


def _parse_float(value: object, default: float) -> float:
    """将值解析为浮点数"""

    if value is None:
        return default
    try:
        return float(str(value).strip())
    except ValueError:
        return default


def _parse_int(value: object, default: int) -> int:
    """将值解析为整数"""

    if value is None:
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


def _resolve_command_for_report(command: str | None) -> str:
    """为 doctor 诊断解析命令路径，不执行命令本身"""

    configured = (command or "").strip()
    if not configured:
        return ""
    resolved = shutil.which(configured)
    if resolved:
        return Path(resolved).as_posix()
    return configured


def _command_is_runnable_for_report(command: str | None) -> bool:
    """判断 doctor 报告中的命令是否可被当前系统启动"""

    resolved = _resolve_command_for_report(command)
    if not resolved:
        return False
    if shutil.which(resolved):
        return True
    if "/" in resolved or "\\" in resolved or Path(resolved).is_absolute():
        return Path(resolved).expanduser().exists()
    return False


def _read_json_config(config_path: Path) -> dict:
    """读取 JSON 配置文件"""

    if not config_path.exists():
        raise ConfigurationError(f"未找到配置文件: {config_path}")
    raw_text = config_path.read_text(encoding="utf-8").strip()
    if not raw_text:
        raise ConfigurationError(f"配置文件为空: {config_path}")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"配置文件格式错误: {config_path}") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError(f"配置文件根节点必须是对象: {config_path}")
    return payload


def default_config_payload(paths: AppPaths) -> dict:
    """返回默认配置模板"""

    return {
        "telegram": {
            "bot_token": "",
            "allowed_chat_ids": [],
            "proxy_url": None,
        },
        "copilot": {
            "cli_command": "copilot",
            "model": "gpt-5-mini",
            "available_models": [],
            "timeout_seconds": 3600,
            "allow_all_tools": True,
            "add_workspace_dir": True,
            "reasoning_effort": None,
            "forward_reasoning": True,
        },
        "runtime": {
            "workspace_root": paths.workspace_dir.as_posix(),
            "session_watch_interval_seconds": 2.0,
        },
        "storage": {
            "chat_db_path": paths.chat_db_file.as_posix(),
            "session_db_path": paths.session_db_file.as_posix(),
            "log_file_path": paths.log_file.as_posix(),
        },
        "logging": {
            "log_level": "INFO",
            "console_log_level": "INFO",
            "httpx_log_level": "WARNING",
        },
    }


def write_config(payload: dict, config_path: Path) -> None:
    """写入 JSON 配置"""

    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2)

    if config_path.exists():
        previous = config_path.read_text(encoding="utf-8")
        if previous != content:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = config_path.with_name(f"config.backup-{stamp}.json")
            backup_path.write_text(previous, encoding="utf-8")

    config_path.write_text(content, encoding="utf-8")


def has_config(app_home: Path | None = None) -> bool:
    """判断配置文件是否存在"""

    paths = build_app_paths(app_home)
    return paths.config_file.exists()


def doctor_report(app_home: Path | None = None) -> DoctorReport:
    """返回默认配置目录的诊断结果"""

    paths = build_app_paths(app_home)
    config_path = paths.config_file
    has_cfg = config_path.exists()

    config_status = "missing"
    telegram_token_status = "unknown"
    copilot_cli_command: str | None = None
    copilot_cli_resolved_command: str | None = None
    copilot_cli_runnable: bool | None = None
    copilot_model: str | None = None
    copilot_timeout_seconds: int | None = None
    workspace_root: str | None = None
    runtime_workspace_exists: bool | None = None
    issues: list[str] = []

    if has_cfg:
        try:
            payload = _read_json_config(config_path)
        except ConfigurationError:
            config_status = "invalid"
            telegram_token_status = "invalid"
            issues.append("配置文件不是合法 JSON 对象")
        else:
            config_status = "ok"
            telegram = payload.get("telegram") if isinstance(payload.get("telegram"), dict) else {}
            copilot = payload.get("copilot") if isinstance(payload.get("copilot"), dict) else {}
            runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}

            token = str(telegram.get("bot_token") or "").strip()
            telegram_token_status = "set" if token else "empty"
            if not token:
                issues.append("telegram.bot_token 为空")
            copilot_cli_command = str(copilot.get("cli_command") or "copilot").strip() or "copilot"
            copilot_cli_resolved_command = _resolve_command_for_report(copilot_cli_command)
            copilot_cli_runnable = _command_is_runnable_for_report(copilot_cli_command)
            if not copilot_cli_runnable:
                issues.append(f"Copilot CLI 命令不可执行: {copilot_cli_command}")
            copilot_model = str(copilot.get("model") or "gpt-5-mini").strip() or "gpt-5-mini"
            copilot_timeout_seconds = _parse_int(copilot.get("timeout_seconds"), 3600)
            if copilot_timeout_seconds <= 0:
                issues.append("copilot.timeout_seconds 必须大于 0")
            workspace_root = str(runtime.get("workspace_root") or paths.workspace_dir.as_posix()).strip() or paths.workspace_dir.as_posix()
            runtime_workspace_exists = Path(workspace_root).expanduser().exists()
            if not runtime_workspace_exists:
                issues.append(f"工作区不存在: {workspace_root}")
    else:
        issues.append("配置文件不存在")

    return DoctorReport(
        app_home=paths.home_dir,
        config_path=config_path,
        has_config=has_cfg,
        config_status=config_status,
        telegram_token_status=telegram_token_status,
        copilot_cli_command=copilot_cli_command,
        copilot_cli_resolved_command=copilot_cli_resolved_command,
        copilot_cli_runnable=copilot_cli_runnable,
        copilot_model=copilot_model,
        copilot_timeout_seconds=copilot_timeout_seconds,
        workspace_root=workspace_root,
        data_dir_exists=paths.data_dir.exists(),
        logs_dir_exists=paths.logs_dir.exists(),
        workspace_dir_exists=paths.workspace_dir.exists(),
        runtime_workspace_exists=runtime_workspace_exists,
        issues=issues,
    )


def load_settings(app_home: Path | None = None) -> Settings:
    """加载并返回应用配置"""

    paths = build_app_paths(app_home)
    ensure_app_dirs(paths)

    payload = _read_json_config(paths.config_file)
    telegram = payload.get("telegram") if isinstance(payload.get("telegram"), dict) else {}
    copilot = payload.get("copilot") if isinstance(payload.get("copilot"), dict) else {}
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    storage = payload.get("storage") if isinstance(payload.get("storage"), dict) else {}
    logging_cfg = payload.get("logging") if isinstance(payload.get("logging"), dict) else {}

    token = str(telegram.get("bot_token") or "").strip()
    if not token:
        raise ConfigurationError(f"配置项 telegram.bot_token 为空: {paths.config_file}")

    workspace_root = Path(str(runtime.get("workspace_root") or paths.workspace_dir.as_posix())).expanduser().resolve()
    chat_db_path = Path(str(storage.get("chat_db_path") or paths.chat_db_file.as_posix())).expanduser().resolve()
    session_db_path = Path(str(storage.get("session_db_path") or paths.session_db_file.as_posix())).expanduser().resolve()
    log_file_path = Path(str(storage.get("log_file_path") or paths.log_file.as_posix())).expanduser().resolve()

    workspace_root.mkdir(parents=True, exist_ok=True)
    chat_db_path.parent.mkdir(parents=True, exist_ok=True)
    session_db_path.parent.mkdir(parents=True, exist_ok=True)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        telegram_bot_token=token,
        allowed_chat_ids=_parse_chat_ids(telegram.get("allowed_chat_ids")),
        workspace_root=workspace_root,
        chat_db_path=chat_db_path,
        session_db_path=session_db_path,
        telegram_proxy_url=(str(telegram.get("proxy_url") or "").strip() or None),
        copilot_cli_command=(str(copilot.get("cli_command") or "copilot").strip() or "copilot"),
        copilot_cli_model=(str(copilot.get("model") or "gpt-5-mini").strip() or "gpt-5-mini"),
        copilot_cli_timeout_seconds=_parse_int(copilot.get("timeout_seconds"), 3600),
        copilot_cli_allow_all_tools=_parse_bool(copilot.get("allow_all_tools"), True),
        copilot_cli_add_workspace_dir=_parse_bool(copilot.get("add_workspace_dir"), True),
        copilot_cli_reasoning_effort=(str(copilot.get("reasoning_effort") or "").strip() or None),
        copilot_cli_forward_reasoning=_parse_bool(copilot.get("forward_reasoning"), True),
        copilot_available_models=_parse_models_array(copilot.get("available_models")),
        log_file_path=log_file_path,
        log_level=(str(logging_cfg.get("log_level") or "INFO").strip() or "INFO").upper(),
        console_log_level=(str(logging_cfg.get("console_log_level") or "INFO").strip() or "INFO").upper(),
        httpx_log_level=(str(logging_cfg.get("httpx_log_level") or "WARNING").strip() or "WARNING").upper(),
        session_watch_interval_seconds=_parse_float(runtime.get("session_watch_interval_seconds"), 2.0),
        app_home=paths.home_dir,
        config_path=paths.config_file,
    )
