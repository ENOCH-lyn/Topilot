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
    fake_copilot = tmp_path / "copilot.cmd"
    fake_copilot.write_text("@echo off\n", encoding="utf-8")
    workspace = tmp_path / "workspace-root"
    workspace.mkdir()
    payload = default_config_payload(paths)
    payload["telegram"]["bot_token"] = "telegram-token"
    payload["copilot"]["cli_command"] = fake_copilot.as_posix()
    payload["copilot"]["model"] = "gpt-5"
    payload["copilot"]["timeout_seconds"] = 180
    payload["runtime"]["workspace_root"] = workspace.as_posix()

    write_config(payload, paths.config_file)

    report = doctor_report(paths.home_dir)

    assert report.has_config is True
    assert report.config_status == "ok"
    assert report.telegram_token_status == "set"
    assert report.copilot_cli_command == fake_copilot.as_posix()
    assert report.copilot_cli_resolved_command == fake_copilot.as_posix()
    assert report.copilot_cli_runnable is True
    assert report.copilot_model == "gpt-5"
    assert report.copilot_timeout_seconds == 180
    assert report.workspace_root == workspace.as_posix()
    assert report.runtime_workspace_exists is True
    assert report.issues == []


def test_doctor_report_collects_configuration_issues(tmp_path: Path) -> None:
    paths = build_app_paths(tmp_path / "app")
    missing_workspace = tmp_path / "missing-workspace"
    payload = default_config_payload(paths)
    payload["telegram"]["bot_token"] = ""
    payload["copilot"]["cli_command"] = (tmp_path / "missing-copilot.cmd").as_posix()
    payload["copilot"]["timeout_seconds"] = 0
    payload["runtime"]["workspace_root"] = missing_workspace.as_posix()

    write_config(payload, paths.config_file)

    report = doctor_report(paths.home_dir)

    assert report.config_status == "ok"
    assert report.telegram_token_status == "empty"
    assert report.copilot_cli_runnable is False
    assert report.runtime_workspace_exists is False
    assert "telegram.bot_token 为空" in report.issues
    assert "copilot.timeout_seconds 必须大于 0" in report.issues
    assert f"工作区不存在: {missing_workspace.as_posix()}" in report.issues


def test_run_doctor_prints_extended_health_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    paths = build_app_paths(tmp_path / "app")
    fake_copilot = tmp_path / "copilot.cmd"
    fake_copilot.write_text("@echo off\n", encoding="utf-8")
    paths.workspace_dir.mkdir(parents=True, exist_ok=True)
    payload = default_config_payload(paths)
    payload["telegram"]["bot_token"] = "telegram-token"
    payload["copilot"]["cli_command"] = fake_copilot.as_posix()
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
    assert f"copilot_cli_command={fake_copilot.as_posix()}" in captured.out
    assert f"copilot_cli_resolved_command={fake_copilot.as_posix()}" in captured.out
    assert "copilot_cli_runnable=True" in captured.out
    assert "copilot_model=gpt-5" in captured.out
    assert "copilot_timeout_seconds=3600" in captured.out
    assert "issues=none" in captured.out
