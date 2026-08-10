"""Security regression tests.

Each test corresponds to a finding in the security assessment. The threat
model is a local desktop application: the adversary is a malicious *file*
(a note or an archive that arrived from somewhere else), not a network peer.
"""

from __future__ import annotations

import json
import stat
import sys
import zipfile

import pytest

from notsucky.models.note import Note, is_valid_id
from notsucky.services import backup
from notsucky.services.file_manager import (
    MAX_NOTE_FILE_BYTES,
    FileManager,
)
from notsucky.services.note_service import NoteService
from notsucky.utils import paths


class TestPathTraversal:
    """A03 Injection — a note id becomes a file name."""

    @pytest.mark.parametrize(
        "hostile",
        [
            "../../../etc/passwd",
            "..\\..\\Windows\\System32\\config",
            "/etc/shadow",
            "C:\\Windows\\win.ini",
            "note/../../escape",
            "\\\\server\\share\\file",
        ],
    )
    def test_hostile_ids_are_rejected(self, hostile) -> None:
        assert is_valid_id(hostile) is False
        with pytest.raises(ValueError):
            FileManager.path_for(hostile)

    def test_a_hostile_id_in_a_file_is_repaired_on_load(self, notes_dir) -> None:
        (notes_dir / "evil.json").write_text(
            json.dumps({"id": "../../../pwned", "title": "evil"}), encoding="utf-8"
        )
        notes = FileManager.load_all()
        assert len(notes) == 1
        assert is_valid_id(notes[0].id)
        assert ".." not in notes[0].id

    def test_saving_a_repaired_note_stays_inside_the_notes_dir(self, notes_dir) -> None:
        note = Note(id="../../escape", title="evil")
        path = FileManager.save_note(note)
        assert path.parent.resolve() == notes_dir.resolve()

    def test_nothing_is_written_outside_the_notes_dir(self, notes_dir, tmp_path) -> None:
        before = {p for p in tmp_path.rglob("*") if p.is_file()}
        for hostile in ("../escape", "../../escape", "a/b"):
            note = Note()
            object.__setattr__(note, "id", hostile)
            with pytest.raises((ValueError, OSError)):
                FileManager.save_note(note)
        after = {p for p in tmp_path.rglob("*") if p.is_file()}
        assert after == before


class TestResourceExhaustion:
    """A04/A05 — untrusted input must not be read unbounded into memory."""

    def test_an_oversized_note_file_is_skipped(self, notes_dir) -> None:
        payload = json.dumps({"id": "huge0001", "title": "x", "content": "A" * 200})
        big = notes_dir / "huge0001.json"
        big.write_text(payload, encoding="utf-8")
        # Pad past the limit without allocating it in the test.
        with big.open("a", encoding="utf-8") as fh:
            fh.write(" " * (MAX_NOTE_FILE_BYTES + 1 - big.stat().st_size))

        assert big.stat().st_size > MAX_NOTE_FILE_BYTES
        assert FileManager.load_all() == []
        assert FileManager.load_by_id("huge0001") is None

    def test_one_oversized_file_does_not_hide_the_others(self, notes_dir) -> None:
        NoteService.create(title="Legitimate")
        big = notes_dir / "huge0001.json"
        big.write_bytes(b"{" + b" " * (MAX_NOTE_FILE_BYTES + 10))

        assert [n.title for n in FileManager.load_all()] == ["Legitimate"]

    def test_a_file_at_the_limit_is_still_read(self, notes_dir) -> None:
        note = NoteService.create(title="Fine")
        assert (notes_dir / f"{note.id}.json").stat().st_size < MAX_NOTE_FILE_BYTES
        assert FileManager.load_by_id(note.id) is not None

    def test_note_content_is_capped_regardless_of_file_content(self, notes_dir) -> None:
        payload = json.dumps({"id": "big00001", "content": "A" * 2_000_000})
        (notes_dir / "big00001.json").write_text(payload, encoding="utf-8")
        loaded = FileManager.load_by_id("big00001")
        assert loaded is not None
        assert len(loaded.content) == 1_000_000


class TestArchiveHandling:
    """A08 Data integrity — an archive may not be one we produced."""

    def test_zip_slip_is_refused(self, notes_dir, tmp_path) -> None:
        evil = paths.backup_dir() / "slip.zip"
        with zipfile.ZipFile(evil, "w") as archive:
            archive.writestr("../../escaped.json", '{"title": "pwned"}')
            archive.writestr("/absolute.json", '{"title": "pwned"}')
            archive.writestr("nested/dir.json", '{"title": "pwned"}')

        assert backup.restore_backup(evil) == 0
        assert not (tmp_path / "escaped.json").exists()
        assert not (notes_dir.parent / "escaped.json").exists()
        assert list(notes_dir.glob("*.json")) == []

    def test_a_zip_bomb_entry_is_skipped(self, notes_dir) -> None:
        """A 200 KB archive previously wrote 200 MB to disk."""
        bomb = paths.backup_dir() / "bomb.zip"
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("bomb0001.json", "0" * (backup.MAX_RESTORE_ENTRY_BYTES + 1))

        assert backup.restore_backup(bomb, overwrite=True) == 0
        assert not (notes_dir / "bomb0001.json").exists()

    def test_the_total_expansion_is_capped(self, notes_dir, monkeypatch) -> None:
        monkeypatch.setattr(backup, "MAX_RESTORE_TOTAL_BYTES", 1000)
        archive_path = paths.backup_dir() / "many.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for index in range(10):
                archive.writestr(f"n{index:07d}.json", "0" * 400)

        with pytest.raises(OSError):
            backup.restore_backup(archive_path)

    def test_too_many_entries_is_refused(self, notes_dir, monkeypatch) -> None:
        monkeypatch.setattr(backup, "MAX_RESTORE_ENTRIES", 2)
        archive_path = paths.backup_dir() / "many.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for index in range(5):
                archive.writestr(f"n{index:07d}.json", "{}")

        with pytest.raises(OSError):
            backup.restore_backup(archive_path)

    def test_a_legitimate_archive_still_restores(self, notes_dir) -> None:
        note = NoteService.create(title="Real", content="body")
        archive_path = backup.create_backup()
        FileManager.purge_note(note)

        assert backup.restore_backup(archive_path) == 1
        assert FileManager.load_by_id(note.id).title == "Real"


class TestFilePermissions:
    """A01 Broken access control, in its local form: other users on the box."""

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes are not meaningful on Windows")
    def test_the_notes_directory_is_owner_only(self, notes_dir) -> None:
        mode = stat.S_IMODE(notes_dir.stat().st_mode)
        assert mode & 0o077 == 0, f"notes dir is {oct(mode)}, group/other can reach it"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes are not meaningful on Windows")
    def test_note_files_are_not_world_readable(self, notes_dir) -> None:
        note = NoteService.create(title="private", content="secret")
        mode = stat.S_IMODE((notes_dir / f"{note.id}.json").stat().st_mode)
        assert mode & 0o007 == 0, f"note file is {oct(mode)}"

    def test_restricting_permissions_never_raises(self, tmp_path) -> None:
        paths.restrict_permissions(tmp_path / "does-not-exist")


class TestSensitiveDataInLogs:
    """A09 Logging failures — the logs must not become a copy of the notes."""

    def test_note_content_is_never_logged(self, caplog, notes_dir) -> None:
        secret = "correct-horse-battery-staple"
        with caplog.at_level("DEBUG"):
            note = NoteService.create(title="Bank PIN", content=secret)
            NoteService.update_content(note, secret + " updated")
            NoteService.delete(note)

        assert secret not in caplog.text

    def test_note_titles_are_never_logged(self, caplog, notes_dir) -> None:
        with caplog.at_level("DEBUG"):
            note = NoteService.create(title="Divorce lawyer appointment")
            NoteService.update_title(note, "Still sensitive")
            NoteService.delete(note)

        assert "Divorce" not in caplog.text
        assert "Still sensitive" not in caplog.text

    def test_ids_are_logged_so_support_still_works(self, caplog, notes_dir) -> None:
        with caplog.at_level("INFO"):
            note = NoteService.create(title="Anything")
        assert note.id in caplog.text


class TestDeserialization:
    """A08 — the JSON is data, and must never become behaviour."""

    @pytest.mark.parametrize(
        "payload",
        [
            '{"__class__": "os.system", "title": "x"}',
            '{"id": {"$ref": "evil"}, "title": "x"}',
            '{"title": {"nested": "object"}}',
            '{"minimized": "yes please"}',
            '{"order": [1, 2, 3]}',
            "[1, 2, 3]",
            '"just a string"',
            "null",
        ],
    )
    def test_hostile_payloads_never_execute_or_crash(self, notes_dir, payload) -> None:
        (notes_dir / "abcd1234.json").write_text(payload, encoding="utf-8")
        FileManager.load_all()  # must not raise
        FileManager.load_by_id("abcd1234")

    def test_unknown_keys_cannot_set_attributes(self) -> None:
        note = Note.from_dict({"title": "ok", "file_path": "/etc/passwd", "__dict__": {}})
        assert note.title == "ok"
        assert "passwd" not in str(note.file_path)
