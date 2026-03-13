from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppPaths:
    """应用目录结构"""

    home_dir: Path
    config_file: Path
    data_dir: Path
    logs_dir: Path
    workspace_dir: Path
    chat_db_file: Path
    session_db_file: Path
    log_file: Path


def build_app_paths(home_dir: Path | None = None) -> AppPaths:
    """构建应用目录路径"""

    root = (home_dir or Path.home() / ".copilot-in-telegram").expanduser().resolve()
    data_dir = root / "data"
    logs_dir = root / "logs"
    workspace_dir = root / "workspace"
    return AppPaths(
        home_dir=root,
        config_file=root / "config.json",
        data_dir=data_dir,
        logs_dir=logs_dir,
        workspace_dir=workspace_dir,
        chat_db_file=data_dir / "chats.json",
        session_db_file=data_dir / "sessions.json",
        log_file=logs_dir / "app.log",
    )


def ensure_app_dirs(paths: AppPaths) -> None:
    """确保目录存在"""

    paths.home_dir.mkdir(parents=True, exist_ok=True)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.workspace_dir.mkdir(parents=True, exist_ok=True)
