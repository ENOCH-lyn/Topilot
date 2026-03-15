from __future__ import annotations
"""兼容入口模块"""

from topilot.cli.main import main as cli_main


def main() -> None:
    """转发到 CLI 入口"""

    cli_main()


if __name__ == "__main__":
    main()
