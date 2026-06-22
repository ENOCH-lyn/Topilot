from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from topilot.config import (
    ConfigurationError,
    default_config_payload,
    doctor_report,
    has_config,
    load_settings,
    write_config,
)
from topilot.feishu_bot import start_feishu_bot
from topilot.logging_setup import configure_logging
from topilot.paths import build_app_paths, ensure_app_dirs
from topilot.telegram_bot import build_application


logger = logging.getLogger(__name__)


def _prompt(prompt: str, default: str | None = None, required: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""


def _prompt_bool(prompt: str, default: bool) -> bool:
    default_hint = "Y/n" if default else "y/N"
    value = input(f"{prompt} ({default_hint}): ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "1", "true", "on"}


def run_init(force: bool = False) -> int:
    """初始化配置文件"""

    paths = build_app_paths()
    ensure_app_dirs(paths)

    if paths.config_file.exists() and not force:
        print(f"配置已存在: {paths.config_file}")
        print("如需覆盖请执行: topilot init --force")
        return 0

    print("首次配置向导")
    print(f"配置目录: {paths.home_dir}")

    token = _prompt("Telegram Bot Token", required=True)
    chat_ids = _prompt("允许访问的 Chat ID，多个用逗号分隔，留空表示全部允许", default="")
    proxy_url = _prompt("Telegram 代理 URL，可留空", default="")
    feishu_enabled = _prompt_bool("启用 Feishu 通道", default=False)
    feishu_app_id = ""
    feishu_app_secret = ""
    if feishu_enabled:
        feishu_app_id = _prompt("Feishu App ID", required=True)
        feishu_app_secret = _prompt("Feishu App Secret", required=True)
    cli_command = _prompt("Copilot CLI 命令", default="copilot")
    model = _prompt("默认模型", default="gpt-5-mini")
    workspace = _prompt("默认工作区路径", default=paths.workspace_dir.as_posix())
    watch_interval = _prompt("会话追踪轮询间隔秒数", default="2")
    add_workspace = _prompt_bool("Copilot 命令自动附带 --add-dir", default=True)

    payload = default_config_payload(paths)
    payload["telegram"]["enabled"] = True
    payload["telegram"]["bot_token"] = token
    payload["telegram"]["allowed_chat_ids"] = [
        int(item.strip())
        for item in chat_ids.split(",")
        if item.strip().lstrip("-").isdigit()
    ]
    payload["telegram"]["proxy_url"] = proxy_url or None
    payload["feishu"]["enabled"] = feishu_enabled
    payload["feishu"]["app_id"] = feishu_app_id
    payload["feishu"]["app_secret"] = feishu_app_secret
    payload["copilot"]["cli_command"] = cli_command
    payload["copilot"]["model"] = model
    payload["copilot"]["add_workspace_dir"] = add_workspace
    payload["runtime"]["workspace_root"] = Path(workspace).expanduser().resolve().as_posix()
    try:
        payload["runtime"]["session_watch_interval_seconds"] = float(watch_interval)
    except ValueError:
        payload["runtime"]["session_watch_interval_seconds"] = 2.0

    write_config(payload, paths.config_file)
    print(f"配置已写入: {paths.config_file}")
    return 0


def run_doctor(app_home: Path | None = None) -> int:
    """输出启动前诊断信息"""

    report = doctor_report(app_home=app_home)
    print(f"app_home={report.app_home}")
    print(f"config={report.config_path}")
    print(f"has_config={report.has_config}")
    print(f"config_status={report.config_status}")
    print(f"telegram_enabled={report.telegram_enabled}")
    print(f"telegram_token={report.telegram_token_status}")
    print(f"feishu_enabled={report.feishu_enabled}")
    print(f"feishu_app={report.feishu_app_status}")
    print(f"data_dir_exists={report.data_dir_exists}")
    print(f"logs_dir_exists={report.logs_dir_exists}")
    print(f"workspace_dir_exists={report.workspace_dir_exists}")
    if report.workspace_root is not None:
        print(f"workspace_root={report.workspace_root}")
    if report.runtime_workspace_exists is not None:
        print(f"runtime_workspace_exists={report.runtime_workspace_exists}")
    if report.copilot_cli_command is not None:
        print(f"copilot_cli_command={report.copilot_cli_command}")
    if report.copilot_cli_resolved_command is not None:
        print(f"copilot_cli_resolved_command={report.copilot_cli_resolved_command}")
    if report.copilot_cli_runnable is not None:
        print(f"copilot_cli_runnable={report.copilot_cli_runnable}")
    if report.copilot_model is not None:
        print(f"copilot_model={report.copilot_model}")
    if report.copilot_timeout_seconds is not None:
        print(f"copilot_timeout_seconds={report.copilot_timeout_seconds}")
    if report.issues:
        print("issues=" + "；".join(report.issues))
    else:
        print("issues=none")
    return 0


def run_start() -> int:
    """加载配置并启动机器人"""

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(str(exc))
        return 1

    configure_logging(settings)
    if settings.telegram_proxy_url:
        os.environ.setdefault("HTTP_PROXY", settings.telegram_proxy_url)
        os.environ.setdefault("HTTPS_PROXY", settings.telegram_proxy_url)
        os.environ.setdefault("ALL_PROXY", settings.telegram_proxy_url)

    feishu_runner = None
    if settings.feishu_enabled:
        feishu_runner = start_feishu_bot(settings)

    if settings.telegram_enabled:
        while True:
            application = build_application(settings)
            application.run_polling(
                poll_interval=0.0,
                timeout=30,
                bootstrap_retries=-1,
                drop_pending_updates=False,
                close_loop=False,
            )
            bot_data = getattr(application, "bot_data", {})
            if not bot_data.get("telegram_restart_requested"):
                break
            logger.warning("Telegram polling 已停止，2 秒后重建应用")
            time.sleep(2.0)
        return 0

    if feishu_runner is not None:
        while True:
            time.sleep(3600)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="topilot", description="Copilot Cli in Telegram")

    sub = parser.add_subparsers(dest="command")

    init_parser = sub.add_parser("init", help="初始化配置")
    init_parser.add_argument("--force", action="store_true", help="覆盖已存在配置")

    sub.add_parser("start", help="启动机器人")
    sub.add_parser("doctor", help="检查默认配置目录与配置状态")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "init":
        raise SystemExit(run_init(force=bool(args.force)))

    if args.command == "doctor":
        raise SystemExit(run_doctor())

    if not has_config():
        print("检测到首次运行，开始配置")
        code = run_init(force=False)
        if code != 0:
            raise SystemExit(code)

    raise SystemExit(run_start())
