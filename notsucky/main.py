"""NotSucky Notes - application entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from notsucky import __version__

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notsucky-notes",
        description="A sticky notes application with a searchable, reorderable dashboard.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--notes-dir",
        metavar="PATH",
        help="Directory to store notes in (overrides the NOTSUCKY_NOTES_DIR variable).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console and file log verbosity (default: INFO).",
    )
    parser.add_argument(
        "--no-log-file", action="store_true", help="Log to the console only."
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the daily backup snapshot taken at startup.",
    )
    parser.add_argument(
        "--backup-now",
        action="store_true",
        help="Write a backup snapshot immediately, then exit.",
    )
    parser.add_argument(
        "--list-backups",
        action="store_true",
        help="List available backup snapshots, then exit.",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print environment and storage details for a bug report, then exit.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print statistics about your notes, then exit.",
    )
    parser.add_argument(
        "--export",
        metavar="DIR",
        help="Export every note as an individual file into DIR, then exit.",
    )
    parser.add_argument(
        "--export-format",
        default="md",
        choices=["md", "txt"],
        help="Format for --export (default: md).",
    )
    return parser


def run_backup_command(args: argparse.Namespace) -> int | None:
    """Handle the console subcommands. Returns an exit code, or None.

    None means no such command was requested and the GUI should start. These
    run without a QApplication so they work over SSH and in cron.
    """
    from notsucky.services import backup

    if getattr(args, "diagnostics", False):
        from notsucky.utils.diagnostics import format_diagnostics

        print(format_diagnostics())
        return 0

    if getattr(args, "stats", False):
        from notsucky.services.statistics import format_report

        print(format_report())
        return 0

    if getattr(args, "export", None):
        from notsucky.services import export as export_service

        written = export_service.export_all(
            Path(args.export), getattr(args, "export_format", "md")
        )
        if not written:
            print("No notes to export.")
            return 0
        print(f"Exported {len(written)} note(s) to {Path(args.export).resolve()}")
        return 0

    if args.list_backups:
        backups = backup.list_backups()
        if not backups:
            print("No backups yet.")
            return 0
        for path in backups:
            size_kb = max(1, path.stat().st_size // 1024)
            print(f"{path.name}  {size_kb} KB  {path}")
        return 0

    if args.backup_now:
        created = backup.create_backup()
        if created is None:
            print("Nothing to back up.")
            return 0
        print(f"Wrote {created}")
        return 0

    return None


def main(argv: list[str] | None = None) -> int:
    """Run the application. Returns the process exit code."""
    args = build_parser().parse_args(argv)

    # Imported here so that --help and --version stay fast and do not require
    # a working Qt installation or a display.
    from notsucky.utils.logging_config import setup_logging
    from notsucky.utils.paths import notes_dir, set_notes_dir

    if args.notes_dir:
        set_notes_dir(args.notes_dir)

    log_path = setup_logging(
        level=getattr(logging, args.log_level), to_file=not args.no_log_file
    )

    try:
        store = notes_dir()
    except OSError as exc:
        logger.critical("Cannot open the notes directory: %s", exc)
        _fatal(f"Cannot open the notes directory:\n\n{exc}")
        return 1

    backup_exit = run_backup_command(args)
    if backup_exit is not None:
        return backup_exit

    from PySide6.QtWidgets import QApplication

    from notsucky.services.note_service import NoteService
    from notsucky.utils.diagnostics import (
        install_crash_handler,
        install_qt_message_handler,
        timed,
    )
    from notsucky.views.icon import app_icon

    # Installed before the first widget exists, so a failure during startup
    # is reported rather than printed to a console nobody is watching.
    install_qt_message_handler()
    install_crash_handler(log_path)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("NotSucky Notes")
    app.setApplicationDisplayName("NotSucky Notes")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("NotSucky")
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())

    logger.info("NotSucky Notes %s starting; notes in %s", __version__, store)
    if log_path is not None:
        logger.info("Logging to %s", log_path)

    with timed("Startup maintenance"):
        NoteService.run_maintenance(backup=not args.no_backup)

    from notsucky.views.dashboard import DashboardWindow

    with timed("Dashboard startup"):
        window = DashboardWindow()
        window.show()
    return app.exec()


def _fatal(message: str) -> None:
    """Show a blocking error dialog, falling back to stderr."""
    try:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(None, "NotSucky Notes", message)
    except Exception:
        print(message, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
