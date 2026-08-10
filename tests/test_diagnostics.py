"""Tests for observability: timings, Qt message routing, crash handling,
and the support report."""

from __future__ import annotations

import logging
import sys

import pytest

from notsucky.services.note_service import NoteService
from notsucky.utils import diagnostics


class TestTiming:
    def test_the_duration_is_logged(self, caplog) -> None:
        with caplog.at_level(logging.INFO), diagnostics.timed("Widget assembly"):
            pass
        assert "Widget assembly took" in caplog.text
        assert "ms" in caplog.text

    def test_timing_survives_an_exception(self, caplog) -> None:
        with caplog.at_level(logging.INFO):  # noqa: SIM117 - clarity over nesting
            with pytest.raises(ValueError), diagnostics.timed("Failing step"):
                raise ValueError("boom")
        assert "Failing step took" in caplog.text


class TestDiagnosticsReport:
    def test_it_reports_the_environment(self) -> None:
        report = diagnostics.collect_diagnostics()
        assert report["python"] == sys.version.split()[0]
        assert report["version"]
        assert "notes_dir" in report

    def test_it_counts_the_store(self, notes_dir) -> None:
        for index in range(3):
            NoteService.create(title=f"n{index}")
        NoteService.delete(NoteService.create(title="deleted"))

        report = diagnostics.collect_diagnostics()
        assert report["note_count"] == 3
        assert report["trash_count"] == 1
        assert report["notes_bytes"] > 0

    def test_it_reports_the_active_notes_dir(self, notes_dir) -> None:
        assert str(notes_dir) == diagnostics.collect_diagnostics()["notes_dir"]

    def test_it_includes_qt_versions(self) -> None:
        pytest.importorskip("PySide6")
        report = diagnostics.collect_diagnostics()
        assert report["pyside6"]
        assert report["qt"]

    def test_formatting_is_plain_aligned_text(self, notes_dir) -> None:
        text = diagnostics.format_diagnostics()
        assert "version" in text
        assert " : " in text
        assert len(text.splitlines()) >= 8

    def test_the_report_leaks_no_note_content(self, notes_dir) -> None:
        """It is meant to be pasted into a public issue."""
        NoteService.create(title="Mortgage rate", content="account 12345678")

        text = diagnostics.format_diagnostics()
        assert "Mortgage" not in text
        assert "12345678" not in text

    def test_a_missing_store_does_not_raise(self, tmp_path) -> None:
        from notsucky.utils import paths

        paths.set_notes_dir(tmp_path / "never-created")
        assert diagnostics.collect_diagnostics()["notes_dir"]


class TestCrashHandler:
    @pytest.fixture(autouse=True)
    def _restore_hook(self):
        original = sys.excepthook
        diagnostics._crash_hook_installed = False
        yield
        sys.excepthook = original
        diagnostics._crash_hook_installed = False

    def test_installing_replaces_the_hook(self) -> None:
        original = sys.excepthook
        diagnostics.install_crash_handler()
        assert sys.excepthook is not original

    def test_installing_twice_is_a_no_op(self) -> None:
        diagnostics.install_crash_handler()
        installed = sys.excepthook
        diagnostics.install_crash_handler()
        assert sys.excepthook is installed

    def test_the_previous_hook_is_still_called(self) -> None:
        seen = []
        sys.excepthook = lambda *args: seen.append(args)
        diagnostics.install_crash_handler()

        sys.excepthook(ValueError, ValueError("boom"), None)
        assert len(seen) == 1

    def test_the_crash_is_logged(self, caplog) -> None:
        sys.excepthook = lambda *args: None
        diagnostics.install_crash_handler()

        with caplog.at_level(logging.CRITICAL):
            sys.excepthook(ValueError, ValueError("kaboom"), None)
        assert "kaboom" in caplog.text
        assert "Unhandled ValueError" in caplog.text

    def test_keyboard_interrupt_is_passed_straight_through(self, caplog) -> None:
        seen = []
        sys.excepthook = lambda *args: seen.append(args)
        diagnostics.install_crash_handler()

        with caplog.at_level(logging.CRITICAL):
            sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        assert seen and "Unhandled" not in caplog.text


class TestQtMessageRouting:
    def test_the_handler_installs(self) -> None:
        pytest.importorskip("PySide6")
        diagnostics.install_qt_message_handler()  # must not raise

    def test_qt_warnings_reach_python_logging(self, caplog) -> None:
        pytest.importorskip("PySide6")
        from PySide6.QtCore import qWarning

        diagnostics.install_qt_message_handler()
        with caplog.at_level(logging.WARNING, logger="qt"):
            qWarning("something Qt is unhappy about")
        assert "something Qt is unhappy about" in caplog.text

    def test_known_noise_is_dropped(self, caplog) -> None:
        pytest.importorskip("PySide6")
        from PySide6.QtCore import qWarning

        diagnostics.install_qt_message_handler()
        with caplog.at_level(logging.DEBUG, logger="qt"):
            qWarning("QFontDatabase: Cannot find font directory /nowhere")
        assert "QFontDatabase" not in caplog.text
