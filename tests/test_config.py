from __future__ import annotations

from pathlib import Path

import pytest

from topilot.config import (
    ConfigurationError,
    default_config_payload,
    load_settings,
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
