"""Tests for backup snapshots, retention, and restore."""

from __future__ import annotations

import zipfile
from unittest import mock

import pytest

from notsucky.models.note import Note
from notsucky.services import backup
from notsucky.services.file_manager import FileManager
from notsucky.services.note_service import NoteService
from notsucky.utils import paths


class TestCreate:
    def test_a_snapshot_contains_every_note(self) -> None:
        for title in ("one", "two", "three"):
            NoteService.create(title=title)

        archive_path = backup.create_backup()
        assert archive_path is not None
        with zipfile.ZipFile(archive_path) as archive:
            assert len(archive.namelist()) == 3

    def test_snapshot_entries_are_flat_json_files(self) -> None:
        note = NoteService.create(title="one")
        with zipfile.ZipFile(backup.create_backup()) as archive:
            assert archive.namelist() == [f"{note.id}.json"]

    def test_snapshot_content_matches_the_note(self) -> None:
        note = NoteService.create(title="Payload", content="body text")
        with zipfile.ZipFile(backup.create_backup()) as archive:
            restored = Note.from_json(archive.read(f"{note.id}.json").decode("utf-8"))
        assert (restored.title, restored.content) == ("Payload", "body text")

    def test_nothing_to_back_up_returns_none(self) -> None:
        assert backup.create_backup() is None

    def test_backups_live_beside_the_notes_not_inside(self) -> None:
        NoteService.create(title="one")
        archive_path = backup.create_backup()
        assert archive_path.parent == paths.backup_dir()
        assert archive_path.parent != FileManager.directory()

    def test_trashed_notes_are_excluded(self) -> None:
        keep = NoteService.create(title="keep")
        NoteService.delete(NoteService.create(title="deleted"))

        with zipfile.ZipFile(backup.create_backup()) as archive:
            assert archive.namelist() == [f"{keep.id}.json"]

    def test_a_failed_write_leaves_no_partial_archive(self) -> None:
        NoteService.create(title="one")
        with mock.patch("zipfile.ZipFile", side_effect=OSError("disk full")):
            assert backup.create_backup() is None
        assert list(paths.backup_dir().glob("*.part")) == []
        assert backup.list_backups() == []


class TestRetention:
    def _make(self, count: int) -> None:
        NoteService.create(title="seed")
        directory = paths.backup_dir()
        for index in range(count):
            path = directory / f"{backup.BACKUP_PREFIX}2026010{index}-000000{backup.BACKUP_SUFFIX}"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("x.json", "{}")

    def test_listing_is_newest_first(self) -> None:
        self._make(3)
        names = [p.name for p in backup.list_backups()]
        assert names == sorted(names, reverse=True)

    def test_pruning_keeps_the_newest(self) -> None:
        self._make(5)
        assert backup.prune_backups(keep=2) == 3
        assert len(backup.list_backups()) == 2

    def test_pruning_under_the_limit_is_a_no_op(self) -> None:
        self._make(2)
        assert backup.prune_backups(keep=10) == 0

    def test_creating_a_backup_prunes_old_ones(self) -> None:
        self._make(backup.MAX_BACKUPS + 3)
        backup.create_backup()
        assert len(backup.list_backups()) <= backup.MAX_BACKUPS

    def test_listing_with_no_backup_dir_is_empty(self) -> None:
        assert backup.list_backups() == []


class TestSchedule:
    def test_the_first_run_takes_a_snapshot(self) -> None:
        NoteService.create(title="one")
        assert backup.backup_if_due() is not None

    def test_a_recent_snapshot_suppresses_the_next(self) -> None:
        NoteService.create(title="one")
        assert backup.backup_if_due() is not None
        assert backup.backup_if_due() is None

    def test_an_old_snapshot_does_not_suppress(self) -> None:
        NoteService.create(title="one")
        backup.create_backup()
        with mock.patch.object(backup, "seconds_since_last_backup", return_value=99_999):
            assert backup.backup_if_due() is not None

    def test_age_is_none_without_backups(self) -> None:
        assert backup.seconds_since_last_backup() is None

    def test_age_is_small_right_after_a_backup(self) -> None:
        NoteService.create(title="one")
        backup.create_backup()
        assert backup.seconds_since_last_backup() < 60


class TestRestore:
    def test_restore_recreates_deleted_notes(self) -> None:
        note = NoteService.create(title="Precious", content="text")
        archive_path = backup.create_backup()

        FileManager.purge_note(note)
        assert FileManager.load_all() == []

        assert backup.restore_backup(archive_path) == 1
        assert FileManager.load_by_id(note.id).title == "Precious"

    def test_restore_leaves_existing_notes_alone_by_default(self) -> None:
        note = NoteService.create(title="Original")
        archive_path = backup.create_backup()
        NoteService.update_title(note, "Edited since the backup")

        assert backup.restore_backup(archive_path) == 0
        assert FileManager.load_by_id(note.id).title == "Edited since the backup"

    def test_overwrite_replaces_existing_notes(self) -> None:
        note = NoteService.create(title="Original")
        archive_path = backup.create_backup()
        NoteService.update_title(note, "Edited since the backup")

        assert backup.restore_backup(archive_path, overwrite=True) == 1
        assert FileManager.load_by_id(note.id).title == "Original"

    def test_a_tampered_archive_cannot_escape_the_notes_dir(self, notes_dir, tmp_path) -> None:
        evil = paths.backup_dir() / "evil.zip"
        with zipfile.ZipFile(evil, "w") as archive:
            archive.writestr("../../escaped.json", '{"title": "pwned"}')
            archive.writestr("subdir/nested.json", '{"title": "nested"}')

        assert backup.restore_backup(evil) == 0
        assert not (tmp_path / "escaped.json").exists()
        assert not (notes_dir.parent / "escaped.json").exists()

    def test_non_json_entries_are_skipped(self) -> None:
        archive_path = paths.backup_dir() / "mixed.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("readme.txt", "hello")
            archive.writestr("abcd1234.json", '{"id": "abcd1234", "title": "kept"}')

        assert backup.restore_backup(archive_path) == 1
        assert [n.title for n in FileManager.load_all()] == ["kept"]

    def test_a_corrupt_archive_raises(self) -> None:
        broken = paths.backup_dir() / "broken.zip"
        broken.write_text("not a zip", encoding="utf-8")
        with pytest.raises(OSError):
            backup.restore_backup(broken)

    def test_round_trip_preserves_everything(self) -> None:
        note = NoteService.create(title="Full", content="body")
        NoteService.update_geometry(note, 12, 34, 400, 300)
        NoteService.change_color(note, "Purple")
        archive_path = backup.create_backup()

        FileManager.purge_note(note)
        backup.restore_backup(archive_path)

        restored = FileManager.load_by_id(note.id)
        assert restored.to_dict() == note.to_dict()
