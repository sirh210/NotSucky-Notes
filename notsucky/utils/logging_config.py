"""Logging setup.

Configured explicitly from :func:`notsucky.main.main` rather than at import
time, so importing the package never has side effects.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from notsucky.utils.paths import log_dir

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
MAX_LOG_BYTES = 1_000_000
BACKUP_COUNT = 3

_configured = False


def setup_logging(level: int = logging.INFO, *, to_file: bool = True) -> Path | None:
    """Configure root logging once. Returns the log file path, if any.

    A failure to open the log file is never fatal: the application falls back
    to console-only logging.
    """
    global _configured
    if _configured:
        return None

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(console)

    log_path: Path | None = None
    if to_file:
        try:
            directory = log_dir()
            directory.mkdir(parents=True, exist_ok=True)
            log_path = directory / "notsucky.log"
            file_handler = logging.handlers.RotatingFileHandler(
                log_path, maxBytes=MAX_LOG_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
            )
            file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
            root.addHandler(file_handler)
        except OSError as exc:
            log_path = None
            root.warning("File logging disabled (%s)", exc)

    _configured = True
    return log_path
