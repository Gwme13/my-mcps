"""Centralized logging with rotating file handler.

Logs include latency and token counts so the user can verify that delegation
actually saves tokens/time compared to handling the task directly.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_FILE = LOG_DIR / "mcp.log"


def get_logger(name: str, level: str = "DEBUG") -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger
