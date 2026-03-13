from __future__ import annotations
"""兼容入口模块"""

from copilot_in_telegram.cli.main import main as cli_main


def main() -> None:
    """转发到 CLI 入口"""

    cli_main()


if __name__ == "__main__":
    main()
