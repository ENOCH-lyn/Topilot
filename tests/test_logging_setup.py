from __future__ import annotations

import logging
from pathlib import Path

from topilot.logging_setup import _to_level, configure_logging


def test_to_level_uses_logging_constants_and_fallback() -> None:
    assert _to_level("debug", logging.INFO) == logging.DEBUG
    assert _to_level("not-a-level", logging.INFO) == logging.INFO


def test_configure_logging_replaces_handlers_and_sets_target_levels(make_settings) -> None:
    settings = make_settings(log_level="DEBUG", console_log_level="ERROR", httpx_log_level="INFO")
    root_logger = logging.getLogger()
    httpx_logger = logging.getLogger("httpx")
    previous_handlers = list(root_logger.handlers)
    previous_level = root_logger.level
    previous_httpx_level = httpx_logger.level
    stale_handler = logging.NullHandler()
    root_logger.addHandler(stale_handler)

    try:
        configure_logging(settings)

        handlers = list(root_logger.handlers)
        assert stale_handler not in handlers
        assert len(handlers) == 2
        assert root_logger.level == logging.DEBUG
        assert httpx_logger.level == logging.INFO

        file_handler = next(handler for handler in handlers if hasattr(handler, "baseFilename"))
        console_handler = next(handler for handler in handlers if not hasattr(handler, "baseFilename"))
        assert file_handler.level == logging.DEBUG
        assert console_handler.level == logging.ERROR
        assert Path(settings.log_file_path).exists()
    finally:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()
        for handler in previous_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(previous_level)
        httpx_logger.setLevel(previous_httpx_level)
