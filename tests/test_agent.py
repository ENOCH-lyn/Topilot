from __future__ import annotations

import asyncio
from pathlib import Path

from topilot.agent import AssistantPlanner, CopilotCliDiagnostic, StreamState


def test_build_copilot_argv_keeps_session_id_model_and_workspace(make_settings, monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "workspace-a"
    workspace.mkdir()
    extra_dir = "C:/sandbox/desktop"
    planner = AssistantPlanner(
        make_settings(
            copilot_cli_command="copilot.bat",
            copilot_cli_reasoning_effort="high",
            copilot_additional_allowed_dirs=[extra_dir],
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
    assert "--session-id" in argv
    assert "--resume" not in argv
    assert "session-123" in argv
    assert "--model" in argv
    assert "gpt-5" in argv
    assert "--reasoning-effort" in argv
    assert "high" in argv
    assert "--add-dir" in argv
    assert workspace.as_posix() in argv
    assert extra_dir in argv
    prompt_value = argv[argv.index("-p") + 1]
    assert prompt_value == r"line1\nline2"


def test_build_copilot_argv_uses_allow_all_paths_when_enabled(make_settings, monkeypatch) -> None:
    extra_dir = "C:/sandbox/desktop"
    planner = AssistantPlanner(
        make_settings(
            copilot_cli_command="copilot.bat",
            copilot_cli_allow_all_paths=True,
            copilot_additional_allowed_dirs=[extra_dir],
        )
    )
    monkeypatch.setattr(planner, "_resolve_copilot_command", lambda: "copilot.bat")

    argv = planner._build_copilot_argv("hello", "session-123", model="gpt-5")

    assert "--allow-all-paths" in argv
    assert "--add-dir" not in argv


def test_allowed_dirs_for_command_deduplicates_paths(make_settings) -> None:
    workspace_dir = "C:/sandbox/project"
    extra_dir = "C:/sandbox/desktop"
    planner = AssistantPlanner(
        make_settings(
            copilot_additional_allowed_dirs=[
                extra_dir,
                extra_dir,
                "   ",
            ]
        )
    )

    assert planner._allowed_dirs_for_command(workspace_dir) == [
        workspace_dir,
        extra_dir,
    ]


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


def test_build_copilot_config_help_argv_wraps_powershell_script(make_settings, monkeypatch) -> None:
    planner = AssistantPlanner(make_settings(copilot_cli_command="C:/Copilot/copilot.ps1"))
    monkeypatch.setattr(planner, "_resolve_copilot_command", lambda: "C:/Copilot/copilot.ps1")

    argv = planner._build_copilot_config_help_argv()

    assert argv == [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "C:/Copilot/copilot.ps1",
        "help",
        "config",
    ]


def test_parse_available_models_from_help_deduplicates_choices(make_settings) -> None:
    planner = AssistantPlanner(make_settings())
    help_text = """
    Usage: copilot [options]
      --model <model>  Select model (choices: "gpt-5-mini", "gpt-5", "gpt-5-mini")
      --output-format <format>
    """

    assert planner._parse_available_models_from_help(help_text) == ["gpt-5-mini", "gpt-5"]


def test_parse_available_models_from_help_does_not_read_other_option_choices(make_settings) -> None:
    planner = AssistantPlanner(make_settings())
    help_text = """
    Usage: copilot [options]
      --model <model>                       Set the AI model to use
      --mouse[=value]                       Enable mouse support
      --output-format <format>              Output format
                                            (choices: "text", "json")
    """

    assert planner._parse_available_models_from_help(help_text) == []


def test_parse_available_models_from_config_help_reads_model_section(make_settings) -> None:
    planner = AssistantPlanner(make_settings())
    help_text = """
    Configuration Settings:

      `logLevel`: log level for CLI.

      `model`: AI model to use for Copilot CLI.
        - "claude-sonnet-4.6"
        - "gpt-5.4"
        - "gpt-5-mini"
        - "gpt-5.4"

      `mouse`: whether to enable mouse support.
        - "on"
        - "off"
    """

    assert planner._parse_available_models_from_config_help(help_text) == [
        "claude-sonnet-4.6",
        "gpt-5.4",
        "gpt-5-mini",
    ]


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


def test_diagnostic_render_without_optional_sections() -> None:
    diagnostic = CopilotCliDiagnostic(
        ready=True,
        summary="Copilot CLI 已就绪（model=gpt-5）",
        model="gpt-5",
        configured_command="copilot",
        resolved_command="C:/tools/copilot.cmd",
        workspace_dir="C:/workspace",
        workspace_exists=True,
        timeout_seconds=15,
        allow_all_tools=True,
        add_workspace_dir=True,
        reasoning_effort=None,
        issues=[],
    )

    rendered = diagnostic.render()

    assert "后端状态: Copilot CLI 已就绪（model=gpt-5）" in rendered
    assert "可用模型:" not in rendered
    assert "待处理:" not in rendered


def test_option_block_and_choice_parsing_helpers(make_settings) -> None:
    planner = AssistantPlanner(make_settings())
    text = """
      --model <model>  Select model
                       (choices: "gpt-5", "gpt-5-mini")
      --output-format <format>
                       (choices: "text", "json")
    """

    block = planner._extract_option_block(text, "--model")

    assert "--output-format" not in block
    assert planner._parse_choices_from_block(block) == ["gpt-5", "gpt-5-mini"]
    assert planner._parse_choices_from_block("no choices here") == []


def test_stream_and_summary_helpers_cover_reasoning_messages_and_generic_payloads(make_settings) -> None:
    planner = AssistantPlanner(make_settings())
    state = StreamState()

    reply_events = planner._stream_events_from_item(
        {"type": "assistant.message", "data": {"content": [{"text": "完整回复"}]}},
        state,
    )
    reasoning_events = planner._stream_events_from_item(
        {"type": "assistant.reasoning", "data": {"content": [{"text": "**推理过程**"}]}},
        state,
    )
    generic_events = planner._stream_events_from_item(
        {"type": "planner.step", "data": {"title": "读取配置", "message": "已完成"}},
        state,
    )
    noisy_events = planner._stream_events_from_item(
        {"type": "session.info", "data": {"toolName": "report_intent", "message": "intent logged"}},
        state,
    )

    assert reply_events[0].kind == "reply"
    assert reply_events[0].text == "完整回复"
    assert reasoning_events[0].text == "思考: 推理过程"
    assert generic_events[0].text == "[步骤] 读取配置\n已完成"
    assert noisy_events == []


def test_tool_start_success_and_failure_helpers_cover_multiple_branches(make_settings) -> None:
    planner = AssistantPlanner(make_settings())
    state = StreamState()

    start_command = planner._summarize_tool_start(
        {
            "toolName": "powershell",
            "toolCallId": "call-command",
            "arguments": {"command": "Get-Process"},
        },
        state,
    )
    complete_command = planner._summarize_tool_complete(
        {
            "toolCallId": "call-command",
            "success": True,
            "result": {"content": "line-1\r\nline-2\r\n<exited with 0>"},
        },
        state,
    )
    failure_read = planner._summarize_tool_complete(
        {
            "toolName": "view",
            "success": False,
            "arguments": {"path": "src/topilot/config.py"},
            "error": {"message": "permission denied"},
        },
        state,
    )

    assert start_command == "执行命令：Get-Process"
    assert "命令输出（command=Get-Process）" in complete_command
    assert "line-1" in complete_command
    assert "读取失败：src/topilot/config.py" in failure_read


def test_tool_formatting_helpers_cover_specialized_outputs(make_settings) -> None:
    planner = AssistantPlanner(make_settings())

    assert planner._format_tool_start("view", {"path": "src/topilot/agent.py"}) == "读取文件：src/topilot/agent.py"
    assert planner._format_tool_start("glob", {"path": "src", "pattern": "*.py"}) == "列出目录：src（pattern=*.py）"
    assert planner._format_tool_start("grep", {"query": "bot", "path": "src"}) == "检索代码：bot（path=src）"
    assert planner._format_tool_start("task", {"agent_type": "reader", "description": "scan logs"}) == "启动子任务（agent=reader）：scan logs"
    assert planner._format_tool_start("web_fetch", {"url": "https://example.com"}) == "读取资源：https://example.com"
    assert planner._format_tool_start("fetch_copilot_cli_documentation", {}) == "获取 Copilot CLI 文档"

    assert planner._format_tool_success("list_powershell", {}, {"result": {"content": "alpha\nbeta"}}).startswith("PowerShell 会话列表 | 共 2 条")
    assert planner._format_tool_success("grep", {"query": "bot"}, {"result": {"content": "a\nb\nc"}}).startswith("代码检索结果（query=bot）")
    assert planner._format_tool_success("web_fetch", {"url": "https://example.com"}, {"result": {"content": "body"}}).startswith("网页抓取结果（url=https://example.com）")
    assert planner._format_tool_success("task", {"agent_type": "reader", "description": "scan"}, {"result": {"content": "done"}}).startswith("子任务结果")
    assert planner._format_tool_success("fetch_copilot_cli_documentation", {}, {"result": {"content": "ignored"}}) == "文档已获取：Copilot CLI 文档（README + 帮助）"
    assert planner._format_tool_success("view", {"path": "src/topilot/agent.py"}, {"result": {"content": "ignored"}}) == ""

    assert planner._format_tool_failure("powershell", {"command": "Get-Item"}, {"error": {"message": "boom"}}).startswith("命令执行失败（command=Get-Item）")
    assert planner._format_tool_failure("view", {"path": "a.txt"}, {"error": {"message": "boom"}}).startswith("读取失败：a.txt")
    assert planner._format_tool_failure("grep", {}, {"error": {"message": "boom"}}) == "grep 失败：boom"


def test_list_and_text_helpers_cover_edge_cases(make_settings) -> None:
    planner = AssistantPlanner(make_settings())
    long_lines = "\n".join(f"item-{index}" for index in range(10))
    large_output = "Output too large to read at once. Saved to: C:/temp/out.txt\nline-1\nline-2\nline-3\nline-4"

    assert planner._summarize_list_result("", title="目录列表") == "目录列表：空"
    assert planner._summarize_list_result("No files matched pattern", title="目录列表") == "目录列表：无匹配项"
    assert "输出过大，已保存：C:/temp/out.txt" in planner._summarize_list_result(large_output, title="目录列表")
    assert "其余 4 条已省略" in planner._summarize_list_result(long_lines, title="目录列表", max_items=6)
    assert planner._format_command_output("", "") == "命令输出：无输出"
    assert planner._compact_reasoning(" **reasoning** ") == "reasoning"
    assert planner._shorten_single_line("a b c", 10) == "a b c"
    assert planner._event_prefix("assistant.message") == "[助手]"
    assert planner._event_prefix("error.runtime") == "[错误]"


def test_json_text_and_runtime_helpers_cover_nested_and_fallback_inputs(make_settings, monkeypatch, tmp_path: Path) -> None:
    planner = AssistantPlanner(make_settings(copilot_cli_command="custom"))
    existing_command = tmp_path / "tool.cmd"
    existing_command.write_text("@echo off\n", encoding="utf-8")

    def fake_which(name: str) -> str | None:
        if name == "copilot":
            return "C:/resolved/copilot.cmd"
        return None

    monkeypatch.setattr("topilot.agent.shutil.which", fake_which)

    assert planner._pick_first_string({"nested": {"message": "ok"}}, ["message"]) == "ok"
    assert planner._compact_json({"a": 1, "b": "x"}) == '{"a":1,"b":"x"}'
    assert planner._compact_json(None) == ""
    assert planner._extract_delta_text({"content": {"chunk": "delta"}}) == "delta"
    assert planner._extract_tool_arguments('{"path":"src"}') == {"path": "src"}
    assert planner._extract_tool_arguments("{broken") == {}
    assert planner._build_context_suffix({"path": "src", "glob": "*.py"}, [("path", "path"), ("glob", "glob")]) == "（path=src, glob=*.py）"
    assert planner._tool_name_has_any("run_in_terminal", {"run", "grep"}) is True
    assert planner._is_noisy_payload({"toolName": "report_intent"}) is True
    assert planner._is_noisy_payload({"message": "intent logged to store"}) is True
    assert planner._looks_like_tool_payload({"toolName": "grep"}) is True
    assert planner._extract_tool_result_text({"result": {"content": "payload"}}) == "payload"
    assert planner._looks_like_file("src/topilot/agent.py") is True
    assert planner._looks_like_file("src/topilot") is False
    assert planner._parse_result_lines("first\r\n<exited with 0>\nsecond") == ["first", "second"]
    assert planner._strip_process_footer("first\nsecond\n<exited with 0>") == "first\nsecond"
    assert planner._resolve_copilot_command() == "C:/resolved/copilot.cmd"
    assert planner._command_is_runnable(existing_command.as_posix()) is True
    assert planner._command_is_runnable("") is False
    assert planner._normalize_prompt_for_command("a\r\nb", "tool.cmd") == r"a\nb"
    assert planner._normalize_prompt_for_command("a\nb", "tool.py") == "a\nb"
    assert "建议: 执行 topilot doctor" in planner._format_cli_failure_message(RuntimeError("very bad"))


def test_extract_copilot_jsonl_parts_and_text_parts(make_settings) -> None:
    planner = AssistantPlanner(make_settings())
    raw = """
    not-json
    {"type":"assistant.reasoning","data":{"content":[{"text":"reason-1"},{"content":{"text":"reason-2"}}]}}
    {"type":"assistant.message","data":{"content":[{"value":"hello"},{"message":"world"}]}}
    {"type":"assistant.message","data":{"content":"final"}}
    """

    message, reasoning = planner._extract_copilot_jsonl_parts(raw)

    assert message == "final"
    assert reasoning == "reason-1\nreason-2"
    assert planner._extract_text_parts({"content": [{"text": "x"}, {"value": "y"}], "other": {"message": "z"}}) == ["x", "y", "z"]
