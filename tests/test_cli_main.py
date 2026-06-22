from __future__ import annotations

import argparse
import os
import runpy

import pytest

import topilot.cli.main as cli_main
from topilot.config import ConfigurationError


class FakeParser:
    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args

    def parse_args(self) -> argparse.Namespace:
        return self._args


def test_prompt_returns_default_and_required_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["", "", "value"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert cli_main._prompt("Token", default="fallback") == "fallback"
    assert cli_main._prompt("Token", required=True) == "value"


def test_prompt_bool_supports_default_false_and_true_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["", "n", "yes"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    assert cli_main._prompt_bool("Enable", default=True) is True
    assert cli_main._prompt_bool("Enable", default=True) is False
    assert cli_main._prompt_bool("Enable", default=False) is True


def test_build_parser_exposes_expected_subcommands() -> None:
    parser = cli_main._build_parser()
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))

    assert {"init", "start", "doctor"} <= set(subparsers.choices)


def test_run_start_sets_proxy_and_runs_application(make_settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(telegram_proxy_url="http://127.0.0.1:10808")
    calls: dict[str, object] = {}

    class FakeApplication:
        def run_polling(self, **kwargs) -> None:
            calls["run_polling_kwargs"] = kwargs

    monkeypatch.setattr(cli_main, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_main, "configure_logging", lambda current: calls.setdefault("settings", current))
    monkeypatch.setattr(cli_main, "start_feishu_bot", lambda current: calls.setdefault("feishu", current))
    monkeypatch.setattr(cli_main, "build_application", lambda current: FakeApplication())
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)

    assert cli_main.run_start() == 0
    assert calls["settings"] is settings
    assert "feishu" not in calls
    assert calls["run_polling_kwargs"] == {
        "poll_interval": 0.0,
        "timeout": 30,
        "bootstrap_retries": -1,
        "drop_pending_updates": False,
        "close_loop": False,
    }
    assert os.environ["HTTP_PROXY"] == settings.telegram_proxy_url
    assert os.environ["HTTPS_PROXY"] == settings.telegram_proxy_url
    assert os.environ["ALL_PROXY"] == settings.telegram_proxy_url


def test_run_start_rebuilds_telegram_application_when_restart_is_requested(make_settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings()
    calls: list[str] = []

    class FakeApplication:
        def __init__(self, restart_requested: bool) -> None:
            self.bot_data = {"telegram_restart_requested": restart_requested}

        def run_polling(self, **kwargs) -> None:
            calls.append("run")
            calls.append(f"close_loop:{kwargs['close_loop']}")

    applications = iter([FakeApplication(True), FakeApplication(False)])

    monkeypatch.setattr(cli_main, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_main, "configure_logging", lambda current: calls.append("logging"))
    monkeypatch.setattr(cli_main, "start_feishu_bot", lambda current: calls.append("feishu"))
    monkeypatch.setattr(cli_main, "build_application", lambda current: next(applications))
    monkeypatch.setattr(cli_main.time, "sleep", lambda seconds: calls.append(f"sleep:{seconds}"))

    assert cli_main.run_start() == 0
    assert calls == ["logging", "run", "close_loop:False", "sleep:2.0", "run", "close_loop:False"]


def test_run_start_launches_feishu_before_telegram_when_both_enabled(make_settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    calls: list[str] = []

    class FakeApplication:
        def run_polling(self, **kwargs) -> None:
            calls.append("telegram")

    monkeypatch.setattr(cli_main, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_main, "configure_logging", lambda current: calls.append("logging"))
    monkeypatch.setattr(cli_main, "start_feishu_bot", lambda current: calls.append("feishu"))
    monkeypatch.setattr(cli_main, "build_application", lambda current: FakeApplication())

    assert cli_main.run_start() == 0
    assert calls == ["logging", "feishu", "telegram"]


def test_run_start_supports_feishu_only_mode(make_settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(
        telegram_enabled=False,
        telegram_bot_token=None,
        feishu_enabled=True,
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
    )
    calls: list[str] = []

    monkeypatch.setattr(cli_main, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_main, "configure_logging", lambda current: calls.append("logging"))
    monkeypatch.setattr(cli_main, "start_feishu_bot", lambda current: calls.append("feishu") or object())
    monkeypatch.setattr(cli_main.time, "sleep", lambda seconds: (_ for _ in ()).throw(SystemExit(0)))

    with pytest.raises(SystemExit) as excinfo:
        cli_main.run_start()

    assert excinfo.value.code == 0
    assert calls == ["logging", "feishu"]


def test_run_start_returns_error_when_configuration_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_main, "load_settings", lambda: (_ for _ in ()).throw(ConfigurationError("bad config")))

    assert cli_main.run_start() == 1
    assert "bad config" in capsys.readouterr().out


def test_main_dispatches_init_and_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_main, "_build_parser", lambda: FakeParser(argparse.Namespace(command="init", force=True)))
    monkeypatch.setattr(cli_main, "run_init", lambda force: 12)
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
    assert excinfo.value.code == 12

    monkeypatch.setattr(cli_main, "_build_parser", lambda: FakeParser(argparse.Namespace(command="doctor")))
    monkeypatch.setattr(cli_main, "run_doctor", lambda: 34)
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
    assert excinfo.value.code == 34


def test_main_runs_init_then_start_on_first_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(cli_main, "_build_parser", lambda: FakeParser(argparse.Namespace(command=None)))
    monkeypatch.setattr(cli_main, "has_config", lambda: False)
    monkeypatch.setattr(cli_main, "run_init", lambda force: calls.append(f"init:{force}") or 0)
    monkeypatch.setattr(cli_main, "run_start", lambda: calls.append("start") or 56)

    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()

    assert excinfo.value.code == 56
    assert calls == ["init:False", "start"]
    assert "检测到首次运行，开始配置" in capsys.readouterr().out


def test_main_runs_start_directly_when_config_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_main, "_build_parser", lambda: FakeParser(argparse.Namespace(command=None)))
    monkeypatch.setattr(cli_main, "has_config", lambda: True)
    monkeypatch.setattr(cli_main, "run_start", lambda: 78)

    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()

    assert excinfo.value.code == 78


def test_cli_dunder_main_invokes_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr("topilot.cli.main.main", lambda: called.append("called"))

    runpy.run_module("topilot.cli.__main__", run_name="__main__")

    assert called == ["called"]
