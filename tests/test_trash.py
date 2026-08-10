"""Tests for the trash, undo, and the retention sweep."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from notsucky.models.note import Note
from notsucky.services.file_manager import (
    TRASH_DIR_NAME,
    TRASH_RETENTION_DAYS,
    FileManager,
    StorageError,
    trash_name,
    trash_note_id,
    trash_timestamp,
)
from notsucky.services.note_service import NoteService


def days_ago(days: float) -> float:
    return datetime.now(timezone.utc).timestamp() - days * 86_400


class TestTrashNaming:
    def test_name_carries_id_and_timestamp(self) -> None:
        name = trash_name("abc12345", when=1_700_000_000)
        assert name == "abc12345.1700000000.json"

    def test_round_trip(self) -> None:
        path = Path(trash_name("a-b_C9", when=1_700_000_000))
        assert trash_note_id(path) == "a-b_C9"
        assert trash_timestamp(path) == 1_700_000_000

    @pytest.mark.parametrize(
        "name", ["plain.json", "abc.json", "abc.notanumber.json", "abc.123.txt", "x"]
    )
    def test_unparseable_names_return_none(self, name) -> None:
        assert trash_timestamp(Path(name)) is None or trash_note_id(Path(name)) is None

    def test_ids_with_hyphens_survive(self) -> None:
        path = Path(trash_name("a-b-c-d", when=42))
        assert trash_note_id(path) == "a-b-c-d"


class TestDeleteMovesToTrash:
    def test_delete_returns_the_trash_path(self, notes_dir) -> None:
        note = NoteService.create(title="Doomed")
        trashed = FileManager.delete_note(note)

        assert trashed is not None
        assert trashed.parent == notes_dir / TRASH_DIR_NAME
        assert trashed.exists()

    def test_the_note_leaves_the_notes_directory(self) -> None:
        note = NoteService.create(title="Doomed")
        FileManager.delete_note(note)
        assert FileManager.load_by_id(note.id) is None
        assert FileManager.load_all() == []

    def test_trash_contents_are_not_loaded_as_notes(self, notes_dir) -> None:
        note = NoteService.create(title="Doomed")
        FileManager.delete_note(note)
        NoteService.create(title="Alive")
        assert [n.title for n in FileManager.load_all()] == ["Alive"]

    def test_deleting_a_missing_note_returns_none(self) -> None:
        assert FileManager.delete_note(Note(title="never saved")) is None

    def test_the_trashed_file_still_holds_the_note(self) -> None:
        note = NoteService.create(title="Doomed", content="body")
        trashed = FileManager.delete_note(note)
        recovered = Note.from_json(trashed.read_text(encoding="utf-8"))
        assert (recovered.title, recovered.content) == ("Doomed", "body")

    def test_deleting_twice_only_trashes_once(self) -> None:
        note = NoteService.create(title="Doomed")
        assert FileManager.delete_note(note) is not None
        assert FileManager.delete_note(note) is None

    def test_purge_note_bypasses_the_trash(self) -> None:
        note = NoteService.create(title="Gone")
        assert FileManager.purge_note(note) is True
        assert FileManager.list_trash() == []

    def test_a_failed_move_raises_storage_error(self) -> None:
        note = NoteService.create(title="Doomed")
        with (
            mock.patch("os.replace", side_effect=OSError("locked")),
            pytest.raises(StorageError),
        ):
            FileManager.delete_note(note)


class TestRestore:
    def test_restore_brings_the_note_back(self) -> None:
        note = NoteService.create(title="Oops", content="wanted this")
        trashed = NoteService.delete(note)

        restored = NoteService.undo_delete(trashed)
        assert restored is not None
        assert restored.title == "Oops"
        assert FileManager.load_by_id(note.id).content == "wanted this"

    def test_restore_clears_the_trash_entry(self) -> None:
        note = NoteService.create(title="Oops")
        trashed = NoteService.delete(note)
        NoteService.undo_delete(trashed)

        assert not trashed.exists()
        assert FileManager.list_trash() == []

    def test_restoring_twice_is_harmless(self) -> None:
        note = NoteService.create(title="Oops")
        trashed = NoteService.delete(note)
        NoteService.undo_delete(trashed)
        assert NoteService.undo_delete(trashed) is None

    def test_restore_does_not_clobber_a_reused_id(self) -> None:
        """A new note may have taken the id while the old one sat in trash."""
        note = NoteService.create(title="Original")
        trashed = NoteService.delete(note)

        impostor = Note(id=note.id, title="Newer note")
        FileManager.save_note(impostor)

        restored = FileManager.restore_from_trash(trashed)
        assert restored is not None
        assert restored.id != note.id
        titles = sorted(n.title for n in FileManager.load_all())
        assert titles == ["Newer note", "Original"]

    def test_restore_refuses_paths_outside_the_trash(self, tmp_path) -> None:
        outside = tmp_path / "elsewhere.json"
        outside.write_text('{"id": "abc12345", "title": "smuggled"}', encoding="utf-8")
        assert FileManager.restore_from_trash(outside) is None

    def test_restoring_a_corrupt_entry_returns_none(self, notes_dir) -> None:
        entry = FileManager.trash_directory() / trash_name("abc12345")
        entry.write_text("{{{ not json", encoding="utf-8")
        assert FileManager.restore_from_trash(entry) is None

    def test_restoring_a_missing_entry_returns_none(self, notes_dir) -> None:
        assert FileManager.restore_from_trash(notes_dir / TRASH_DIR_NAME / "gone.1.json") is None


class TestListTrash:
    def test_entries_are_newest_first(self, notes_dir) -> None:
        trash = FileManager.trash_directory()
        for note_id, age in (("old00001", 10), ("new00001", 1), ("mid00001", 5)):
            (trash / trash_name(note_id, when=days_ago(age))).write_text("{}", encoding="utf-8")

        order = [trash_note_id(p) for p in FileManager.list_trash()]
        assert order == ["new00001", "mid00001", "old00001"]

    def test_empty_trash_lists_nothing(self) -> None:
        assert FileManager.list_trash() == []


class TestRetentionSweep:
    def _seed(self, ages_in_days: dict[str, float]) -> None:
        trash = FileManager.trash_directory()
        for note_id, age in ages_in_days.items():
            (trash / trash_name(note_id, when=days_ago(age))).write_text("{}", encoding="utf-8")

    def test_expired_entries_are_purged(self, notes_dir) -> None:
        self._seed({"old00001": TRASH_RETENTION_DAYS + 1, "new00001": 1})

        assert FileManager.purge_trash() == 1
        assert [trash_note_id(p) for p in FileManager.list_trash()] == ["new00001"]

    def test_entries_exactly_at_the_boundary_are_kept(self, notes_dir) -> None:
        self._seed({"edge0001": TRASH_RETENTION_DAYS - 0.01})
        assert FileManager.purge_trash() == 0

    def test_a_custom_age_is_honoured(self, notes_dir) -> None:
        self._seed({"a0000001": 8, "b0000001": 2})
        assert FileManager.purge_trash(max_age_days=7) == 1

    def test_unparseable_entries_are_left_alone(self, notes_dir) -> None:
        """Better to keep an unrecognised file than to guess and delete it."""
        (FileManager.trash_directory() / "mystery.json").write_text("{}", encoding="utf-8")
        assert FileManager.purge_trash(max_age_days=0) == 0

    def test_empty_trash_removes_everything(self, notes_dir) -> None:
        self._seed({"a0000001": 0, "b0000001": 1})
        assert FileManager.empty_trash() == 2
        assert FileManager.list_trash() == []

    def test_purging_an_empty_trash_is_a_no_op(self) -> None:
        assert FileManager.purge_trash() == 0


class TestMaintenance:
    def test_maintenance_sweeps_the_trash(self, notes_dir) -> None:
        trash = FileManager.trash_directory()
        (trash / trash_name("old00001", when=days_ago(90))).write_text("{}", encoding="utf-8")

        NoteService.run_maintenance(backup=False)
        assert FileManager.list_trash() == []

    def test_maintenance_survives_a_failing_sweep(self) -> None:
        with mock.patch.object(FileManager, "purge_trash", side_effect=OSError("nope")):
            NoteService.run_maintenance(backup=False)  # must not raise

    def test_maintenance_survives_a_failing_backup(self) -> None:
        from notsucky.services import backup as backup_service

        with mock.patch.object(
            backup_service, "backup_if_due", side_effect=OSError("nope")
        ):
            NoteService.run_maintenance(backup=True)  # must not raise

    def test_backup_can_be_skipped(self) -> None:
        from notsucky.services import backup as backup_service

        with mock.patch.object(backup_service, "backup_if_due") as spy:
            NoteService.run_maintenance(backup=False)
            spy.assert_not_called()
