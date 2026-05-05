from __future__ import annotations

from pathlib import Path

import pytest

from topilot.cli.main import run_doctor
from topilot.config import (
    ConfigurationError,
    default_config_payload,
    doctor_report,
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


def test_doctor_report_shows_missing_config_and_existing_runtime_dirs(tmp_path: Path) -> None:
    paths = build_app_paths(tmp_path / "app")
    paths.home_dir.mkdir(parents=True, exist_ok=True)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.workspace_dir.mkdir(parents=True, exist_ok=True)

    report = doctor_report(paths.home_dir)

    assert report.has_config is False
    assert report.config_status == "missing"
    assert report.telegram_token_status == "unknown"
    assert report.data_dir_exists is True
    assert report.logs_dir_exists is True
    assert report.workspace_dir_exists is True


def test_doctor_report_extracts_core_fields_from_valid_config(tmp_path: Path) -> None:
    paths = build_app_paths(tmp_path / "app")
    payload = default_config_payload(paths)
    payload["telegram"]["bot_token"] = "telegram-token"
    payload["copilot"]["cli_command"] = "copilot.cmd"
    payload["copilot"]["model"] = "gpt-5"
    payload["runtime"]["workspace_root"] = (tmp_path / "workspace-root").as_posix()

    write_config(payload, paths.config_file)

    report = doctor_report(paths.home_dir)

    assert report.has_config is True
    assert report.config_status == "ok"
    assert report.telegram_token_status == "set"
    assert report.copilot_cli_command == "copilot.cmd"
    assert report.copilot_model == "gpt-5"
    assert report.workspace_root == (tmp_path / "workspace-root").as_posix()


def test_run_doctor_prints_extended_health_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    paths = build_app_paths(tmp_path / "app")
    payload = default_config_payload(paths)
    payload["telegram"]["bot_token"] = "telegram-token"
    payload["copilot"]["cli_command"] = "copilot.cmd"
    payload["copilot"]["model"] = "gpt-5"

    write_config(payload, paths.config_file)
    monkeypatch.setattr("topilot.cli.main.doctor_report", lambda app_home=None: doctor_report(paths.home_dir))

    code = run_doctor()

    captured = capsys.readouterr()
    assert code == 0
    assert "app_home=" in captured.out
    assert "config=" in captured.out
    assert "has_config=True" in captured.out
    assert "config_status=ok" in captured.out
    assert "telegram_token=set" in captured.out
    assert "copilot_cli_command=copilot.cmd" in captured.out
    assert "copilot_model=gpt-5" in captured.out
