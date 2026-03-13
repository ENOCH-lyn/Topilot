from __future__ import annotations

import argparse
import os
from pathlib import Path

from copilot_in_telegram.config import ConfigurationError, default_config_payload, has_config, load_settings, write_config
from copilot_in_telegram.logging_setup import configure_logging
from copilot_in_telegram.paths import build_app_paths, ensure_app_dirs
from copilot_in_telegram.telegram_bot import build_application


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


def run_init(app_home: Path | None = None, force: bool = False) -> int:
    """初始化配置文件"""

    paths = build_app_paths(app_home)
    ensure_app_dirs(paths)

    if paths.config_file.exists() and not force:
        print(f"配置已存在: {paths.config_file}")
        print("如需覆盖请执行: copilot-in-telegram init --force")
        return 0

    print("首次配置向导")
    print(f"配置目录: {paths.home_dir}")

    token = _prompt("Telegram Bot Token", required=True)
    chat_ids = _prompt("允许访问的 Chat ID，多个用逗号分隔，留空表示全部允许", default="")
    proxy_url = _prompt("Telegram 代理 URL，可留空", default="")
    cli_command = _prompt("Copilot CLI 命令", default="copilot")
    model = _prompt("默认模型", default="gpt-4.1")
    workspace = _prompt("默认工作区路径", default=paths.workspace_dir.as_posix())
    watch_interval = _prompt("会话追踪轮询间隔秒数", default="2")
    add_workspace = _prompt_bool("Copilot 命令自动附带 --add-dir", default=True)

    payload = default_config_payload(paths)
    payload["telegram"]["bot_token"] = token
    payload["telegram"]["allowed_chat_ids"] = [
        int(item.strip())
        for item in chat_ids.split(",")
        if item.strip().lstrip("-").isdigit()
    ]
    payload["telegram"]["proxy_url"] = proxy_url or None
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


def run_start(app_home: Path | None = None) -> int:
    """加载配置并启动机器人"""

    try:
        settings = load_settings(app_home=app_home)
    except ConfigurationError as exc:
        print(str(exc))
        return 1

    configure_logging(settings)
    if settings.telegram_proxy_url:
        os.environ.setdefault("HTTP_PROXY", settings.telegram_proxy_url)
        os.environ.setdefault("HTTPS_PROXY", settings.telegram_proxy_url)
        os.environ.setdefault("ALL_PROXY", settings.telegram_proxy_url)

    application = build_application(settings)
    application.run_polling()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="copilot-in-telegram", description="Copilot in Telegram")
    parser.add_argument(
        "--home",
        dest="home",
        default=None,
        help="应用目录，默认 ~/.copilot-in-telegram",
    )

    sub = parser.add_subparsers(dest="command")

    init_parser = sub.add_parser("init", help="初始化配置")
    init_parser.add_argument("--force", action="store_true", help="覆盖已存在配置")

    sub.add_parser("start", help="启动机器人")
    sub.add_parser("config-path", help="显示配置文件路径")
    sub.add_parser("doctor", help="检查运行前配置")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    app_home = Path(args.home).expanduser().resolve() if args.home else None

    if args.command == "init":
        raise SystemExit(run_init(app_home=app_home, force=bool(args.force)))

    if args.command == "config-path":
        print(build_app_paths(app_home).config_file)
        return

    if args.command == "doctor":
        paths = build_app_paths(app_home)
        print(f"app_home={paths.home_dir}")
        print(f"config={paths.config_file}")
        print(f"has_config={has_config(app_home)}")
        return

    if not has_config(app_home):
        print("检测到首次运行，开始配置")
        code = run_init(app_home=app_home, force=False)
        if code != 0:
            raise SystemExit(code)

    raise SystemExit(run_start(app_home=app_home))
