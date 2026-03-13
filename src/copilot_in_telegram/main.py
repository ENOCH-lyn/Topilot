from __future__ import annotations
"""程序入口模块"""

import logging
import os

from copilot_in_telegram.config import ConfigurationError, load_settings
from copilot_in_telegram.logging_setup import configure_logging
from copilot_in_telegram.telegram_bot import build_application

logger = logging.getLogger(__name__)


def main() -> None:
    """加载配置并启动 Telegram 轮询"""

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc

    configure_logging(settings)

    if settings.telegram_proxy_url:
        os.environ.setdefault("HTTP_PROXY", settings.telegram_proxy_url)
        os.environ.setdefault("HTTPS_PROXY", settings.telegram_proxy_url)
        os.environ.setdefault("ALL_PROXY", settings.telegram_proxy_url)

    application = build_application(settings)
    application.run_polling()


if __name__ == "__main__":
    main()
