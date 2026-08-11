"""The two guarantees this application makes about your data.

1. **It never destroys a note you did not explicitly remove.** No timer, no
   sweep, no startup task, no length limit, and no repair path deletes note
   text. The only thing that removes a note is the user, and even that is a
   move to the trash which is kept indefinitely.
2. **It never asks you to sign in**, because it cannot: there is no network
   code in the package at all.

These are the tests that keep both true.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import ClassVar

import pytest

from notsucky.models.note import Note
from notsucky.services import backup
from notsucky.services.file_manager import (
    MAX_NOTE_FILE_BYTES,
    TRASH_RETENTION_DAYS,
    FileManager,
)
from notsucky.services.note_service import NoteService
from notsucky.utils.constants import MAX_CONTENT_LENGTH, MAX_TITLE_LENGTH

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "notsucky"


# ─── Guarantee 1: nothing is deleted behind your back ─────────────


class TestNoAutomaticDeletion:
    def test_starting_up_repeatedly_never_loses_a_note(self, notes_dir) -> None:
        ids = [NoteService.create(title=f"n{i}", content=f"body {i}").id for i in range(10)]

        for _ in range(25):
            NoteService.run_maintenance(backup=False)
            FileManager.load_all()

        assert sorted(n.id for n in FileManager.load_all()) == sorted(ids)

    def test_trash_retention_is_indefinite(self) -> None:
        assert TRASH_RETENTION_DAYS is None

    def test_a_backup_run_never_removes_a_note(self, notes_dir) -> None:
        ids = [NoteService.create(title=f"n{i}").id for i in range(5)]
        backup.create_backup()
        backup.prune_backups(keep=0)  # even wiping every snapshot

        assert sorted(n.id for n in FileManager.load_all()) == sorted(ids)

    def test_loading_a_corrupt_file_does_not_delete_it(self, notes_dir) -> None:
        """Unreadable files are skipped, never cleaned up."""
        broken = notes_dir / "abcd1234.json"
        broken.write_text("{ not json", encoding="utf-8")

        FileManager.load_all()
        FileManager.load_by_id("abcd1234")
        NoteService.run_maintenance(backup=False)

        assert broken.exists()
        assert broken.read_text(encoding="utf-8") == "{ not json"

    def test_an_oversized_file_is_skipped_not_deleted(self, notes_dir) -> None:
        big = notes_dir / "huge0001.json"
        big.write_bytes(b"{" + b" " * (MAX_NOTE_FILE_BYTES + 10))
        size_before = big.stat().st_size

        FileManager.load_all()
        NoteService.run_maintenance(backup=False)

        assert big.exists()
        assert big.stat().st_size == size_before

    def test_a_file_the_app_does_not_understand_is_left_alone(self, notes_dir) -> None:
        stray = notes_dir / "notes-from-another-app.json"
        stray.write_text('{"totally": "different"}', encoding="utf-8")

        FileManager.load_all()
        NoteService.run_maintenance(backup=False)
        assert stray.exists()


class TestDeletionIsAlwaysRecoverable:
    def test_delete_moves_the_file_rather_than_erasing_it(self, notes_dir) -> None:
        note = NoteService.create(title="Doomed", content="precious")
        trashed = NoteService.delete(note)

        assert trashed.exists()
        assert json.loads(trashed.read_text(encoding="utf-8"))["content"] == "precious"

    def test_the_content_is_recoverable_by_hand_from_the_trash(self, notes_dir) -> None:
        """Recovery must not depend on this application still running."""
        note = NoteService.create(title="Doomed", content="precious")
        trashed = NoteService.delete(note)

        recovered = json.loads(trashed.read_text(encoding="utf-8"))
        assert recovered["title"] == "Doomed"
        assert recovered["content"] == "precious"

    def test_undo_restores_it_intact(self, notes_dir) -> None:
        note = NoteService.create(title="Doomed", content="precious")
        before = note.to_dict()

        restored = NoteService.undo_delete(NoteService.delete(note))
        assert restored.to_dict() == before


# ─── Guarantee 1b: no length limit ever discards text ─────────────


class TestExistingTextIsNeverTruncated:
    OVERSIZED = MAX_CONTENT_LENGTH + 5_000

    def test_loading_a_long_note_keeps_every_character(self, notes_dir) -> None:
        payload = json.dumps({"id": "long0001", "content": "x" * self.OVERSIZED})
        (notes_dir / "long0001.json").write_text(payload, encoding="utf-8")

        loaded = FileManager.load_by_id("long0001")
        assert len(loaded.content) == self.OVERSIZED

    def test_saving_a_long_note_back_keeps_every_character(self, notes_dir) -> None:
        """The dangerous case: truncate on load, then persist the stub."""
        payload = json.dumps({"id": "long0001", "content": "x" * self.OVERSIZED})
        (notes_dir / "long0001.json").write_text(payload, encoding="utf-8")

        note = FileManager.load_by_id("long0001")
        NoteService.update_geometry(note, 10, 10)  # any save at all
        FileManager.save_note(note)

        assert len(FileManager.load_by_id("long0001").content) == self.OVERSIZED

    def test_a_long_title_survives_a_round_trip(self, notes_dir) -> None:
        long_title = "T" * (MAX_TITLE_LENGTH + 300)
        payload = json.dumps({"id": "long0002", "title": long_title})
        (notes_dir / "long0002.json").write_text(payload, encoding="utf-8")

        note = FileManager.load_by_id("long0002")
        assert note.title == long_title
        FileManager.save_note(note)
        assert FileManager.load_by_id("long0002").title == long_title

    def test_the_model_does_not_truncate(self) -> None:
        note = Note(title="T" * 5_000, content="c" * self.OVERSIZED)
        assert len(note.title) == 5_000
        assert len(note.content) == self.OVERSIZED

    def test_the_service_does_not_truncate(self, notes_dir) -> None:
        note = NoteService.create()
        NoteService.update_content(note, "y" * self.OVERSIZED)
        NoteService.update_title(note, "T" * 1_000)

        reloaded = FileManager.load_by_id(note.id)
        assert len(reloaded.content) == self.OVERSIZED
        assert len(reloaded.title) == 1_000

    def test_only_trailing_newlines_are_dropped(self, notes_dir) -> None:
        note = NoteService.create()
        NoteService.update_content(note, "  keep  \n\tthis\t\n\n\n")
        assert note.content == "  keep  \n\tthis\t"


class TestEditorPreservesOversizedNotes:
    """Opening a long note in the editor must not shorten it."""

    def test_opening_does_not_shrink_the_content(self, qtbot, notes_dir) -> None:
        pytest.importorskip("PySide6")
        from notsucky.views.note_widget import NoteWidget

        oversized = "x" * (MAX_CONTENT_LENGTH + 5_000)
        payload = json.dumps({"id": "long0001", "content": oversized})
        (notes_dir / "long0001.json").write_text(payload, encoding="utf-8")
        note = FileManager.load_by_id("long0001")

        widget = NoteWidget(note)
        qtbot.addWidget(widget)

        assert len(widget.text_edit.toPlainText()) == len(oversized)
        widget._save_timer.stop()
        widget.flush()
        assert len(FileManager.load_by_id("long0001").content) == len(oversized)

    def test_opening_does_not_shrink_the_title(self, qtbot, notes_dir) -> None:
        pytest.importorskip("PySide6")
        from notsucky.views.note_widget import NoteWidget

        long_title = "T" * (MAX_TITLE_LENGTH + 300)
        note = NoteService.create()
        note.title = long_title
        FileManager.save_note(note)

        widget = NoteWidget(FileManager.load_by_id(note.id))
        qtbot.addWidget(widget)

        assert widget.title_input.text() == long_title
        widget._save_timer.stop()
        widget.flush()
        assert FileManager.load_by_id(note.id).title == long_title

    def test_a_normal_note_is_still_capped_as_it_grows(self, qtbot, notes_dir) -> None:
        pytest.importorskip("PySide6")
        from notsucky.views.note_widget import NoteWidget

        widget = NoteWidget(NoteService.create(content="short"))
        qtbot.addWidget(widget)

        widget.text_edit.setPlainText("z" * (MAX_CONTENT_LENGTH + 10_000))
        assert len(widget.text_edit.toPlainText()) == MAX_CONTENT_LENGTH


# ─── Guarantee 2: there is no sign-in, and cannot be ──────────────


class TestNoNetworkOrSignIn:
    FORBIDDEN_MODULES: ClassVar[frozenset[str]] = frozenset({
        "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx",
        "ftplib", "smtplib", "telnetlib", "xmlrpc", "asyncio", "webbrowser",
    })
    FORBIDDEN_QT_MODULES: ClassVar[frozenset[str]] = frozenset(
        {"QtNetwork", "QtWebEngineWidgets", "QtWebEngineCore", "QtWebSockets"}
    )

    def _imported_modules(self) -> set[str]:
        found: set[str] = set()
        for path in PACKAGE_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    found.add(node.module)
        return found

    def test_no_networking_module_is_imported(self) -> None:
        roots = {name.split(".")[0] for name in self._imported_modules()}
        assert not (roots & self.FORBIDDEN_MODULES), roots & self.FORBIDDEN_MODULES

    def test_no_networking_qt_module_is_imported(self) -> None:
        qt_modules = {
            name.split(".")[1]
            for name in self._imported_modules()
            if name.startswith("PySide6.")
        }
        assert not (qt_modules & self.FORBIDDEN_QT_MODULES)
        assert qt_modules <= {"QtCore", "QtGui", "QtWidgets"}, qt_modules

    def test_the_only_runtime_dependency_is_pyside6(self) -> None:
        requirements = (PACKAGE_ROOT.parent / "requirements.txt").read_text(encoding="utf-8")
        declared = [
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        assert declared == ["PySide6>=6.5.0"]

    @pytest.mark.parametrize(
        "term",
        ["login", "signin", "sign_in", "oauth", "password", "api_key", "access_token", "username"],
    )
    def test_no_credential_handling_anywhere_in_the_package(self, term) -> None:
        for path in PACKAGE_ROOT.rglob("*.py"):
            assert term not in path.read_text(encoding="utf-8").lower(), f"{term} in {path.name}"

    def test_no_url_is_ever_opened(self) -> None:
        for path in PACKAGE_ROOT.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "QDesktopServices" not in source
            assert "openUrl" not in source

    def test_the_app_works_with_no_network_available(self, notes_dir) -> None:
        """Nothing in a normal session can even attempt a connection."""
        import socket

        def refuse(*args, **kwargs):  # pragma: no cover - only fires on failure
            raise AssertionError("the application tried to open a socket")

        original = socket.socket
        socket.socket = refuse
        try:
            note = NoteService.create(title="Offline", content="works")
            NoteService.update_content(note, "still works")
            NoteService.delete(note)
            FileManager.load_all()
            NoteService.run_maintenance(backup=True)
        finally:
            socket.socket = original
