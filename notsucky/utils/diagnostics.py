"""Observability for a desktop application.

There is no server to scrape and no user who will read a stack trace in a
terminal they never opened. What matters instead is that (a) nothing fails
silently, (b) when something does fail the user is told where the evidence is,
and (c) a support conversation can start from one command's output rather than
twenty questions.
"""

from __future__ import annotations

import logging
import platform
import sys
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType

logger = logging.getLogger(__name__)

#: Qt severity -> Python level. Qt is chatty about things that are not
#: actionable, so its "info" is demoted to debug.
_QT_LEVELS = {
    0: logging.DEBUG,     # QtDebugMsg
    4: logging.DEBUG,     # QtInfoMsg
    1: logging.WARNING,   # QtWarningMsg
    2: logging.ERROR,     # QtCriticalMsg
    3: logging.CRITICAL,  # QtFatalMsg
}

#: Qt warnings that are noise in a normal, healthy run.
_QT_IGNORED = (
    "QFontDatabase: Cannot find font directory",
    "Qt no longer ships fonts",
)

_crash_hook_installed = False


# ─── Timing ───────────────────────────────────────────────────────


@contextmanager
def timed(label: str, level: int = logging.INFO) -> Iterator[None]:
    """Log how long a block took.

    Used on the handful of startup steps that can plausibly become slow —
    reading the notes directory, building the first grid — so a user
    reporting "it takes ages to open" produces a log that says which part.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        logger.log(level, "%s took %.0f ms", label, (time.perf_counter() - start) * 1000)


# ─── Qt message routing ───────────────────────────────────────────


def install_qt_message_handler() -> None:
    """Send Qt's own diagnostics through Python logging.

    By default Qt writes to stderr, which for a windowed application goes
    nowhere. Routing it means Qt warnings land in the same rotating log file
    as everything else.
    """
    from PySide6.QtCore import qInstallMessageHandler

    def handler(mode, context, message: str) -> None:  # pragma: no cover - Qt callback
        if any(noise in message for noise in _QT_IGNORED):
            return
        level = _QT_LEVELS.get(int(mode), logging.WARNING)
        location = ""
        if getattr(context, "file", None):
            location = f" ({context.file}:{context.line})"
        logging.getLogger("qt").log(level, "%s%s", message, location)

    qInstallMessageHandler(handler)


# ─── Crash reporting ──────────────────────────────────────────────


def install_crash_handler(log_path=None) -> None:
    """Log uncaught exceptions and tell the user where the log is.

    Without this a crash in a Qt slot prints a traceback to a console the
    user does not have, and the window either dies silently or keeps running
    in a broken state.
    """
    global _crash_hook_installed
    if _crash_hook_installed:
        return

    previous = sys.excepthook

    def hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:  # pragma: no cover - process-level handler
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc, tb)
            return

        logging.getLogger("notsucky.crash").critical(
            "Unhandled %s: %s\n%s",
            exc_type.__name__,
            exc,
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )
        _show_crash_dialog(exc_type, exc, log_path)
        previous(exc_type, exc, tb)

    sys.excepthook = hook
    _crash_hook_installed = True


def _show_crash_dialog(exc_type, exc, log_path) -> None:  # pragma: no cover - needs a display
    """Best-effort dialog. Never allowed to raise from inside a crash path."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is None:
            return
        where = f"\n\nDetails were written to:\n{log_path}" if log_path else ""
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("NotSucky Notes")
        box.setText("Something went wrong.")
        box.setInformativeText(
            f"{exc_type.__name__}: {exc}\n\n"
            f"Your notes are saved as you type, so recent work should be intact."
            f"{where}"
        )
        box.exec()
    except Exception:
        pass


# ─── Support report ───────────────────────────────────────────────


def collect_diagnostics() -> dict[str, object]:
    """Gather everything a support question normally has to ask for."""
    import os

    from notsucky import __version__
    from notsucky.services import backup
    from notsucky.services.file_manager import FileManager
    from notsucky.utils.paths import ENV_NOTES_DIR, backup_dir, log_dir, notes_dir

    report: dict[str, object] = {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "notes_dir": str(notes_dir(create=False)),
        "notes_dir_override": os.environ.get(ENV_NOTES_DIR) or "(not set)",
        "log_dir": str(log_dir()),
        "backup_dir": str(backup_dir(create=False)),
    }

    try:
        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import qVersion

        report["pyside6"] = pyside_version
        report["qt"] = qVersion()
    except Exception as exc:
        report["pyside6"] = f"unavailable ({exc})"

    try:
        directory = notes_dir(create=False)
        note_files = list(directory.glob("*.json")) if directory.is_dir() else []
        report["note_count"] = len(note_files)
        report["notes_bytes"] = sum(p.stat().st_size for p in note_files)
        report["trash_count"] = len(FileManager.list_trash()) if directory.is_dir() else 0
        report["backup_count"] = len(backup.list_backups())
    except OSError as exc:
        report["store_error"] = str(exc)

    return report


def format_diagnostics(report: dict[str, object] | None = None) -> str:
    """Render :func:`collect_diagnostics` as plain text to paste into an issue.

    Deliberately counts and paths only — no note titles or contents, so the
    output is safe to share.
    """
    report = collect_diagnostics() if report is None else report
    width = max(len(key) for key in report)
    lines = [f"{key.ljust(width)} : {value}" for key, value in report.items()]
    return "\n".join(lines)
