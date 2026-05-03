from __future__ import annotations

from pathlib import Path

import pytest

from topilot.config import (
    ConfigurationError,
    default_config_payload,
    load_settings,
    payload_from_legacy_env,
    write_config,
)
from topilot.paths import build_app_paths


def test_write_config_creates_backup_when_content_changes(tmp_path: Path) -> None:
    paths = build_app_paths(tmp_path / "app")
    payload = default_config_payload(paths)
    payload["telegram"]["bot_token"] = "first-token"

    write_config(payload, paths.config_file)

    payload["telegram"]["bot_token"] = "second-token"
    write_config(payload, paths.config_file)

    backups = list(paths.config_file.parent.glob("config.backup-*.json"))
    assert len(backups) == 1
    assert '"bot_token": "first-token"' in backups[0].read_text(encoding="utf-8")


def test_load_settings_reads_json_config_and_creates_runtime_dirs(tmp_path: Path) -> None:
    paths = build_app_paths(tmp_path / "app")
    payload = default_config_payload(paths)
    payload["telegram"]["bot_token"] = "telegram-token"
    payload["telegram"]["allowed_chat_ids"] = [1001, 1002]
    payload["copilot"]["model"] = "gpt-5"
    payload["copilot"]["available_models"] = ["gpt-5", "gpt-5-mini"]
    payload["runtime"]["workspace_root"] = (tmp_path / "custom-workspace").as_posix()

    write_config(payload, paths.config_file)

    settings = load_settings(paths.home_dir)

    assert settings.telegram_bot_token == "telegram-token"
    assert settings.allowed_chat_ids == {1001, 1002}
    assert settings.copilot_cli_model == "gpt-5"
    assert settings.copilot_available_models == ["gpt-5", "gpt-5-mini"]
    assert settings.workspace_root.exists()
    assert settings.chat_db_path.parent.exists()
    assert settings.session_db_path.parent.exists()
    assert settings.log_file_path.parent.exists()


def test_load_settings_requires_non_empty_bot_token(tmp_path: Path) -> None:
    paths = build_app_paths(tmp_path / "app")
    payload = default_config_payload(paths)
    write_config(payload, paths.config_file)

    with pytest.raises(ConfigurationError, match="telegram\\.bot_token 为空"):
        load_settings(paths.home_dir)


def test_payload_from_legacy_env_maps_core_fields(tmp_path: Path) -> None:
    paths = build_app_paths(tmp_path / "app")
    env_values = {
        "TELEGRAM_BOT_TOKEN": "legacy-token",
        "TELEGRAM_ALLOWED_CHAT_IDS": "1,2,-3",
        "TELEGRAM_PROXY_URL": "http://127.0.0.1:1080",
        "COPILOT_CLI_COMMAND": "copilot.ps1",
        "COPILOT_CLI_MODEL": "gpt-5",
        "COPILOT_MODELS": "gpt-5,gpt-5-mini",
        "COPILOT_CLI_TIMEOUT_SECONDS": "99",
        "COPILOT_CLI_ALLOW_ALL_TOOLS": "false",
        "COPILOT_CLI_ADD_WORKSPACE_DIR": "true",
        "COPILOT_CLI_REASONING_EFFORT": "high",
        "COPILOT_CLI_FORWARD_REASONING": "false",
        "SESSION_WATCH_INTERVAL_SECONDS": "3.5",
    }

    payload = payload_from_legacy_env(paths, env_values)

    assert payload["telegram"]["bot_token"] == "legacy-token"
    assert payload["telegram"]["allowed_chat_ids"] == [1, 2, -3]
    assert payload["telegram"]["proxy_url"] == "http://127.0.0.1:1080"
    assert payload["copilot"]["cli_command"] == "copilot.ps1"
    assert payload["copilot"]["model"] == "gpt-5"
    assert payload["copilot"]["available_models"] == ["gpt-5", "gpt-5-mini"]
    assert payload["copilot"]["timeout_seconds"] == 99
    assert payload["copilot"]["allow_all_tools"] is False
    assert payload["copilot"]["add_workspace_dir"] is True
    assert payload["copilot"]["reasoning_effort"] == "high"
    assert payload["copilot"]["forward_reasoning"] is False
    assert payload["runtime"]["session_watch_interval_seconds"] == 3.5
