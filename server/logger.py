# Centralised logging configuration for the Multi-Chat Room Server.

import logging
import logging.handlers
import os
import sys

_RESET = "\033[0m"
_BOLD = "\033[1m"
_GREY = "\033[38;5;240m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_BRED = "\033[1;31m"
_LEVEL_COLOURS = {
    logging.DEBUG: _GREY,
    logging.INFO: _GREEN,
    logging.WARNING: _YELLOW,
    logging.ERROR: _RED,
    logging.CRITICAL: _BRED,
}

_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs",
)
_LOG_FILE = os.path.join(_LOG_DIR, "server.log")

_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3


class _ColourFormatter(logging.Formatter):
    _FMT = "{asctime}  {levelname:<8}  {name:<30}  {message}"
    _DATE_FMT = "%Y-%m-%d %H:%M:%S"

    def __init__(self, use_colour: bool = True) -> None:
        super().__init__(
            fmt=self._FMT,
            datefmt=self._DATE_FMT,
            style="{",
        )
        self._use_colour = use_colour

    def format(self, record: logging.LogRecord) -> str:
        if self._use_colour:
            colour = _LEVEL_COLOURS.get(record.levelno, _RESET)
            record = logging.makeLogRecord(record.__dict__)
            record.levelname = f"{colour}{_BOLD}{record.levelname}{_RESET}"
        return super().format(record)


def setup_logger(level: int = logging.INFO) -> None:
    root = logging.getLogger()

    if root.handlers:
        return

    root.setLevel(level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    use_colour = sys.stdout.isatty()
    console_handler.setFormatter(_ColourFormatter(use_colour=use_colour))

    os.makedirs(_LOG_DIR, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter(
            fmt=_ColourFormatter._FMT,
            datefmt=_ColourFormatter._DATE_FMT,
            style="{",
        )
    )

    root.addHandler(console_handler)
    root.addHandler(file_handler)

    root.info(
        "Logger initialised — level=%s, log file=%s",
        logging.getLevelName(level),
        _LOG_FILE,
    )
