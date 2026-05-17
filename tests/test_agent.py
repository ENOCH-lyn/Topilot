from __future__ import annotations

import asyncio

from topilot.agent import AssistantPlanner, StreamState


def test_build_copilot_argv_keeps_resume_model_and_workspace(make_settings, monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace-a"
    workspace.mkdir()
    planner = AssistantPlanner(
        make_settings(
            copilot_cli_command="copilot.bat",
            copilot_cli_reasoning_effort="high",
        )
    )
    monkeypatch.setattr(planner, "_resolve_copilot_command", lambda: "copilot.bat")

    argv = planner._build_copilot_argv(
        "line1\nline2",
        "session-123",
        model="gpt-5",
        workspace_dir=workspace.as_posix(),
    )

    assert argv[0] == "copilot.bat"
    assert "--resume" in argv
    assert "session-123" in argv
    assert "--model" in argv
    assert "gpt-5" in argv
    assert "--reasoning-effort" in argv
    assert "high" in argv
    assert "--add-dir" in argv
    assert workspace.as_posix() in argv
    prompt_value = argv[argv.index("-p") + 1]
    assert prompt_value == r"line1\nline2"


def test_stream_events_map_tool_logs_and_reply_deltas(make_settings) -> None:
    planner = AssistantPlanner(make_settings())
    state = StreamState()

    start_events = planner._stream_events_from_item(
        {
            "type": "tool.execution_start",
            "data": {
                "toolName": "grep",
                "toolCallId": "call-1",
                "arguments": {"query": "bot token", "path": "src"},
            },
        },
        state,
    )
    complete_events = planner._stream_events_from_item(
        {
            "type": "tool.execution_complete",
            "data": {
                "toolCallId": "call-1",
                "success": True,
                "result": {"content": "src/topilot/config.py:1:token"},
            },
        },
        state,
    )
    reply_events = planner._stream_events_from_item(
        {"type": "assistant.message_delta", "data": {"deltaContent": "测试回复"}},
        state,
    )

    assert start_events[0].kind == "log"
    assert "检索代码" in start_events[0].text
    assert complete_events[0].kind == "log"
    assert "代码检索结果" in complete_events[0].text
    assert reply_events[0].kind == "reply"
    assert reply_events[0].text == "测试回复"


def test_fetch_available_models_falls_back_to_configured_models(make_settings, monkeypatch) -> None:
    planner = AssistantPlanner(make_settings(copilot_available_models=["gpt-5", "gpt-5-mini"]))

    async def _raise_exec(*args, **kwargs):
        raise FileNotFoundError("missing copilot")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_exec)

    assert asyncio.run(planner.fetch_available_models()) == ["gpt-5", "gpt-5-mini"]


def test_fetch_available_models_falls_back_to_default_model_when_config_list_is_empty(make_settings, monkeypatch) -> None:
    planner = AssistantPlanner(make_settings(copilot_cli_model="gpt-5-mini", copilot_available_models=[]))

    async def _raise_exec(*args, **kwargs):
        raise FileNotFoundError("missing copilot")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_exec)

    assert asyncio.run(planner.fetch_available_models()) == ["gpt-5-mini"]


def test_build_copilot_help_argv_wraps_powershell_script(make_settings, monkeypatch) -> None:
    planner = AssistantPlanner(make_settings(copilot_cli_command="C:/Copilot/copilot.ps1"))
    monkeypatch.setattr(planner, "_resolve_copilot_command", lambda: "C:/Copilot/copilot.ps1")

    argv = planner._build_copilot_help_argv()

    assert argv == [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "C:/Copilot/copilot.ps1",
        "--help",
    ]


def test_parse_available_models_from_help_deduplicates_choices(make_settings) -> None:
    planner = AssistantPlanner(make_settings())
    help_text = """
    Usage: copilot [options]
      --model <model>  Select model (choices: "gpt-5-mini", "gpt-5", "gpt-5-mini")
      --output-format <format>
    """

    assert planner._parse_available_models_from_help(help_text) == ["gpt-5-mini", "gpt-5"]
