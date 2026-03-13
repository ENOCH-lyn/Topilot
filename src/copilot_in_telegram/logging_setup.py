from __future__ import annotations
"""应用日志初始化"""

import logging
from logging.handlers import RotatingFileHandler

from copilot_in_telegram.config import Settings


def _to_level(level_name: str, fallback: int) -> int:
    level = getattr(logging, level_name.upper(), None)
    if isinstance(level, int):
        return level
    return fallback


def configure_logging(settings: Settings) -> None:
    """配置文件日志和控制台日志

    - 文件日志：记录更完整的信息（默认 INFO，可通过 LOG_LEVEL 调整）
    - 控制台日志：输出关键进展（默认 INFO，可通过 CONSOLE_LOG_LEVEL 调整）
    """

    file_level = _to_level(settings.log_level, logging.INFO)
    console_level = _to_level(settings.console_log_level, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(min(file_level, console_level))

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    file_handler = RotatingFileHandler(
        settings.log_file_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    httpx_level = _to_level(settings.httpx_log_level, logging.WARNING)
    logging.getLogger("httpx").setLevel(httpx_level)

    logging.getLogger(__name__).info(
        "日志系统已初始化 (file=%s, level=%s, console_level=%s, httpx_level=%s)",
        settings.log_file_path,
        settings.log_level,
        settings.console_log_level,
        settings.httpx_log_level,
    )
