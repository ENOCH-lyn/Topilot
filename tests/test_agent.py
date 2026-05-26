from __future__ import annotations

import asyncio
from pathlib import Path

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


def test_diagnose_copilot_cli_reports_missing_command_and_workspace(make_settings, tmp_path: Path) -> None:
    missing_command = tmp_path / "missing" / "copilot.cmd"
    missing_workspace = tmp_path / "missing-workspace"
    planner = AssistantPlanner(
        make_settings(
            copilot_cli_command=missing_command.as_posix(),
            workspace_root=missing_workspace,
        )
    )

    diagnostic = planner.diagnose_copilot_cli()
    rendered = diagnostic.render(available_models=["gpt-5-mini"])

    assert diagnostic.ready is False
    assert f"命令未找到或不可执行: {missing_command.as_posix()}" in diagnostic.issues
    assert f"工作区不存在: {missing_workspace.as_posix()}" in diagnostic.issues
    assert "后端状态: Copilot CLI 未就绪" in rendered
    assert "可用模型: gpt-5-mini" in rendered
    assert "待处理:" in rendered


def test_diagnose_copilot_cli_ready_includes_runtime_fields(make_settings, tmp_path: Path) -> None:
    fake_copilot = tmp_path / "copilot.cmd"
    fake_copilot.write_text("@echo off\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    planner = AssistantPlanner(
        make_settings(
            copilot_cli_command=fake_copilot.as_posix(),
            workspace_root=workspace,
            copilot_cli_timeout_seconds=42,
            copilot_cli_allow_all_tools=False,
            copilot_cli_add_workspace_dir=False,
            copilot_cli_reasoning_effort="high",
        )
    )

    diagnostic = planner.diagnose_copilot_cli(model="gpt-5")
    rendered = diagnostic.render()

    assert diagnostic.ready is True
    assert diagnostic.summary == "Copilot CLI 已就绪（model=gpt-5）"
    assert f"解析命令: {fake_copilot.as_posix()}" in rendered
    assert "调用参数: timeout=42s, allow_all_tools=False, add_workspace_dir=False, reasoning_effort=high" in rendered


def test_plan_returns_clear_message_when_copilot_cli_is_not_ready(make_settings, tmp_path: Path) -> None:
    missing_command = tmp_path / "missing-copilot.cmd"
    planner = AssistantPlanner(make_settings(copilot_cli_command=missing_command.as_posix()))

    plan = asyncio.run(planner.plan("session-1", [], "hello"))

    assert plan.summary == "Copilot CLI 未就绪"
    assert "当前后端状态: Copilot CLI 未就绪" in plan.assistant_message
    assert f"命令未找到或不可执行: {missing_command.as_posix()}" in plan.assistant_message
    assert "topilot doctor" in plan.assistant_message


class FakePipe:
    def __init__(self, lines: list[bytes] | None = None, block_forever: bool = False) -> None:
        self._lines = list(lines or [])
        self._block_forever = block_forever

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        if self._block_forever:
            await asyncio.sleep(3600)
        return b""


class FakeProcess:
    def __init__(
        self,
        stdout_lines: list[bytes] | None = None,
        stderr_lines: list[bytes] | None = None,
        returncode: int = 0,
        block_forever: bool = False,
    ) -> None:
        self.stdout = FakePipe(stdout_lines, block_forever=block_forever)
        self.stderr = FakePipe(stderr_lines, block_forever=block_forever)
        self.returncode = returncode
        self.killed = False
        self._block_forever = block_forever

    async def wait(self) -> int:
        if self._block_forever and not self.killed:
            await asyncio.sleep(3600)
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_plan_reports_nonzero_copilot_exit_code(make_settings, monkeypatch, tmp_path: Path) -> None:
    fake_copilot = tmp_path / "copilot.cmd"
    fake_copilot.write_text("@echo off\n", encoding="utf-8")
    planner = AssistantPlanner(make_settings(copilot_cli_command=fake_copilot.as_posix()))

    async def _fake_exec(*args, **kwargs) -> FakeProcess:
        return FakeProcess(stderr_lines=[b"authentication failed\n"], returncode=2)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    plan = asyncio.run(planner.plan("session-1", [], "hello"))

    assert plan.summary == "Copilot CLI 调用失败"
    assert "非零退出码 2" in plan.assistant_message
    assert "authentication failed" in plan.assistant_message
    assert "topilot doctor" in plan.assistant_message


def test_plan_reports_empty_copilot_output(make_settings, monkeypatch, tmp_path: Path) -> None:
    fake_copilot = tmp_path / "copilot.cmd"
    fake_copilot.write_text("@echo off\n", encoding="utf-8")
    planner = AssistantPlanner(make_settings(copilot_cli_command=fake_copilot.as_posix()))

    async def _fake_exec(*args, **kwargs) -> FakeProcess:
        return FakeProcess(returncode=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    plan = asyncio.run(planner.plan("session-1", [], "hello"))

    assert plan.summary == "Copilot CLI 调用失败"
    assert "Copilot CLI 返回空结果" in plan.assistant_message
    assert "--output-format json" in plan.assistant_message


def test_plan_reports_copilot_timeout(make_settings, monkeypatch, tmp_path: Path) -> None:
    fake_copilot = tmp_path / "copilot.cmd"
    fake_copilot.write_text("@echo off\n", encoding="utf-8")
    process = FakeProcess(returncode=0, block_forever=True)
    planner = AssistantPlanner(
        make_settings(
            copilot_cli_command=fake_copilot.as_posix(),
            copilot_cli_timeout_seconds=0.01,
        )
    )

    async def _fake_exec(*args, **kwargs) -> FakeProcess:
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    plan = asyncio.run(planner.plan("session-1", [], "hello"))

    assert process.killed is True
    assert plan.summary == "Copilot CLI 调用失败"
    assert "Copilot CLI 超时" in plan.assistant_message
    assert "0.01s" in plan.assistant_message
