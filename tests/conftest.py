from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def make_settings(tmp_path: Path):
    from topilot.config import Settings

    def factory(**overrides):
        app_home = tmp_path / "app-home"
        workspace_root = tmp_path / "workspace"
        chat_db_path = app_home / "data" / "chats.json"
        session_db_path = app_home / "data" / "sessions.json"
        log_file_path = app_home / "logs" / "app.log"
        config_path = app_home / "config.json"

        workspace_root.mkdir(parents=True, exist_ok=True)
        chat_db_path.parent.mkdir(parents=True, exist_ok=True)
        session_db_path.parent.mkdir(parents=True, exist_ok=True)
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

        payload = dict(
            telegram_enabled=True,
            telegram_bot_token="test-token",
            allowed_chat_ids={123456},
            feishu_enabled=False,
            feishu_app_id=None,
            feishu_app_secret=None,
            feishu_allowed_chat_ids=set(),
            feishu_allowed_open_ids=set(),
            feishu_reply_in_thread=True,
            workspace_root=workspace_root,
            chat_db_path=chat_db_path,
            session_db_path=session_db_path,
            telegram_proxy_url=None,
            copilot_cli_command="copilot",
            copilot_cli_model="auto",
            copilot_cli_timeout_seconds=3600,
            copilot_cli_allow_all_tools=True,
            copilot_cli_allow_all_paths=False,
            copilot_cli_add_workspace_dir=True,
            copilot_additional_allowed_dirs=[],
            copilot_cli_reasoning_effort=None,
            copilot_cli_forward_reasoning=True,
            copilot_available_models=["auto"],
            log_file_path=log_file_path,
            log_level="INFO",
            console_log_level="INFO",
            httpx_log_level="WARNING",
            session_watch_interval_seconds=2.0,
            app_home=app_home,
            config_path=config_path,
        )
        payload.update(overrides)
        return Settings(**payload)

    return factory
