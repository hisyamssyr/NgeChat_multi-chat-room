"""
server/logger.py
----------------
Centralised logging configuration for the Multi-Chat Room Server.

Sets up two handlers:
  1. StreamHandler  → colourised output to the terminal (console).
  2. RotatingFileHandler → persistent log in  logs/server.log
     (max 5 MB per file, keeps the last 3 rotated files).

Usage
-----
    from server.logger import setup_logger

    # Call ONCE at server startup, before any other imports
    # that might call logging.getLogger().
    setup_logger(level=logging.DEBUG)   # verbose
    setup_logger()                      # default: INFO

After setup_logger() is called, every module just does:
    import logging
    logger = logging.getLogger(__name__)
    logger.info("...")
"""

import logging
import logging.handlers
import os
import sys

# ── Colour codes for terminal output (ANSI) ───────────────────────────────────

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_GREY   = "\033[38;5;240m"
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_BRED   = "\033[1;31m"   # bold red for CRITICAL

_LEVEL_COLOURS = {
    logging.DEBUG:    _GREY,
    logging.INFO:     _GREEN,
    logging.WARNING:  _YELLOW,
    logging.ERROR:    _RED,
    logging.CRITICAL: _BRED,
}

# Directory where log files are stored (project root / logs /).
_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs",
)
_LOG_FILE = os.path.join(_LOG_DIR, "server.log")

# Maximum size per log file before rotation (bytes).
_MAX_BYTES    = 5 * 1024 * 1024   # 5 MB
_BACKUP_COUNT = 3                  # keep server.log, server.log.1, server.log.2


# ── Custom formatter with optional ANSI colour ────────────────────────────────

class _ColourFormatter(logging.Formatter):
    """
    Logging formatter that prepends ANSI colour codes to the level name
    when writing to a terminal that supports colour.
    """

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
            colour    = _LEVEL_COLOURS.get(record.levelno, _RESET)
            record    = logging.makeLogRecord(record.__dict__)
            record.levelname = f"{colour}{_BOLD}{record.levelname}{_RESET}"
        return super().format(record)


# ── Public API ────────────────────────────────────────────────────────────────

def setup_logger(level: int = logging.INFO) -> None:
    """
    Configure the root logger with console + rotating-file handlers.

    Parameters
    ----------
    level : logging level for both handlers (default: logging.INFO).
            Pass logging.DEBUG for verbose output during development.

    Must be called exactly once, before any logging calls are made.
    Subsequent calls are no-ops (guards against double-initialisation).
    """
    root = logging.getLogger()

    # Guard: if handlers already exist, logger was already initialised.
    if root.handlers:
        return

    root.setLevel(level)

    # ── Console handler ───────────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    # Only use colour when stdout is connected to a real terminal.
    use_colour = sys.stdout.isatty()
    console_handler.setFormatter(_ColourFormatter(use_colour=use_colour))

    # ── File handler (rotating) ───────────────────────────────────────────────
    os.makedirs(_LOG_DIR, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    # Plain formatter for the file — no ANSI codes.
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
