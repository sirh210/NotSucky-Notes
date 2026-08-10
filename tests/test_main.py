"""Tests for the CLI entry point and logging setup."""

from __future__ import annotations

import argparse
import logging

import pytest

from notsucky import __version__
from notsucky.main import build_parser, run_backup_command
from notsucky.services import backup
from notsucky.services.note_service import NoteService
from notsucky.utils import logging_config


class TestArgumentParsing:
    def test_defaults(self) -> None:
        args = build_parser().parse_args([])
        assert args.notes_dir is None
        assert args.log_level == "INFO"
        assert args.no_log_file is False

    def test_notes_dir_is_captured(self) -> None:
        args = build_parser().parse_args(["--notes-dir", "/tmp/x"])
        assert args.notes_dir == "/tmp/x"

    def test_log_level_choices_are_enforced(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--log-level", "LOUD"])

    def test_version_exits_cleanly(self, capsys) -> None:
        with pytest.raises(SystemExit) as excinfo:
            build_parser().parse_args(["--version"])
        assert excinfo.value.code == 0
        assert __version__ in capsys.readouterr().out

    def test_help_mentions_the_notes_dir_flag(self, capsys) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--help"])
        assert "--notes-dir" in capsys.readouterr().out


class TestBackupCommands:
    """These must work without a QApplication, so they run over SSH and cron."""

    @staticmethod
    def _args(**overrides):
        defaults = {"list_backups": False, "backup_now": False}
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_no_backup_flag_means_start_the_gui(self) -> None:
        assert run_backup_command(self._args()) is None

    def test_backup_now_writes_a_snapshot(self, capsys) -> None:
        NoteService.create(title="one")

        assert run_backup_command(self._args(backup_now=True)) == 0
        assert len(backup.list_backups()) == 1
        assert "Wrote" in capsys.readouterr().out

    def test_backup_now_with_no_notes_says_so(self, capsys) -> None:
        assert run_backup_command(self._args(backup_now=True)) == 0
        assert "Nothing to back up" in capsys.readouterr().out

    def test_list_backups_when_empty(self, capsys) -> None:
        assert run_backup_command(self._args(list_backups=True)) == 0
        assert "No backups yet" in capsys.readouterr().out

    def test_list_backups_shows_each_snapshot(self, capsys) -> None:
        NoteService.create(title="one")
        backup.create_backup()

        assert run_backup_command(self._args(list_backups=True)) == 0
        output = capsys.readouterr().out
        assert output.count(backup.BACKUP_PREFIX) >= 1
        assert "KB" in output

    def test_listing_takes_priority_over_creating(self, capsys) -> None:
        NoteService.create(title="one")
        run_backup_command(self._args(list_backups=True, backup_now=True))
        assert backup.list_backups() == []

    def test_the_flags_are_parsed(self) -> None:
        args = build_parser().parse_args(["--backup-now", "--no-backup", "--list-backups"])
        assert (args.backup_now, args.no_backup, args.list_backups) == (True, True, True)


class TestLoggingSetup:
    @pytest.fixture(autouse=True)
    def _reset(self):
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        original_level = root.level
        logging_config._configured = False
        yield
        for handler in root.handlers[:]:
            if handler not in original_handlers:
                handler.close()
                root.removeHandler(handler)
        root.setLevel(original_level)
        logging_config._configured = False

    def test_console_only_adds_no_file_handler(self) -> None:
        assert logging_config.setup_logging(to_file=False) is None
        handlers = logging.getLogger().handlers
        assert not any(
            isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers
        )

    def test_file_logging_creates_a_rotating_log(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(logging_config, "log_dir", lambda: tmp_path / "logs")
        path = logging_config.setup_logging(to_file=True)
        assert path is not None
        assert path.parent.is_dir()

    def test_setup_is_idempotent(self) -> None:
        logging_config.setup_logging(to_file=False)
        before = len(logging.getLogger().handlers)
        logging_config.setup_logging(to_file=False)
        assert len(logging.getLogger().handlers) == before

    def test_an_unwritable_log_dir_is_not_fatal(self, monkeypatch) -> None:
        def explode():
            raise OSError("read-only filesystem")

        monkeypatch.setattr(logging_config, "log_dir", explode)
        assert logging_config.setup_logging(to_file=True) is None
        assert logging.getLogger().handlers  # console logging still works

    def test_level_is_applied(self) -> None:
        logging_config.setup_logging(level=logging.DEBUG, to_file=False)
        assert logging.getLogger().level == logging.DEBUG
