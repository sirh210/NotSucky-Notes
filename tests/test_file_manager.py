"""Tests for the FileManager persistence layer."""

from __future__ import annotations

import json
import os
from unittest import mock

import pytest

from notsucky.models.note import Note
from notsucky.services.file_manager import (
    FileManager,
    StorageError,
    filter_notes,
    sort_for_display,
)


class TestCRUD:
    def test_save_and_load_round_trip(self) -> None:
        note = Note(title="Hello", content="World")
        FileManager.save_note(note)

        loaded = FileManager.load_by_id(note.id)
        assert loaded is not None
        assert loaded.title == "Hello"
        assert loaded.content == "World"

    def test_save_writes_into_the_active_directory(self, notes_dir) -> None:
        note = Note(title="Located")
        path = FileManager.save_note(note)
        assert path == notes_dir / f"{note.id}.json"
        assert path.exists()

    def test_save_overwrites_previous_version(self) -> None:
        note = Note(title="v1")
        FileManager.save_note(note)
        note.title = "v2"
        FileManager.save_note(note)

        assert FileManager.load_by_id(note.id).title == "v2"
        assert len(FileManager.load_all()) == 1

    def test_delete_returns_a_trash_path_only_when_a_file_existed(self) -> None:
        note = Note(title="To Delete")
        FileManager.save_note(note)

        assert FileManager.delete_note(note) is not None
        assert FileManager.delete_note(note) is None
        assert FileManager.load_by_id(note.id) is None

    def test_load_all_returns_every_note(self) -> None:
        for index in range(3):
            FileManager.save_note(Note(title=f"Note {index}"))
        assert len(FileManager.load_all()) == 3

    def test_load_all_is_empty_for_a_fresh_directory(self) -> None:
        assert FileManager.load_all() == []

    def test_load_by_id_returns_none_for_missing(self) -> None:
        assert FileManager.load_by_id("nonexist") is None

    def test_save_all_reports_failures(self) -> None:
        notes = [Note(title="a"), Note(title="b")]
        assert FileManager.save_all(notes) == []


class TestPathSafety:
    @pytest.mark.parametrize("bad_id", ["../escape", "a/b", "", "x" * 100])
    def test_path_for_rejects_unsafe_ids(self, bad_id) -> None:
        with pytest.raises(ValueError):
            FileManager.path_for(bad_id)

    def test_load_by_id_refuses_traversal(self, notes_dir, tmp_path) -> None:
        secret = tmp_path / "secret.json"
        secret.write_text('{"title": "secret"}', encoding="utf-8")
        assert FileManager.load_by_id("../secret") is None

    def test_delete_with_unsafe_id_is_a_no_op(self) -> None:
        note = Note()
        object.__setattr__(note, "id", "../evil")  # bypass __post_init__ repair
        assert FileManager.delete_note(note) is None
        assert FileManager.purge_note(note) is False


class TestAtomicity:
    def test_no_temp_files_remain_after_a_successful_save(self, notes_dir) -> None:
        FileManager.save_note(Note(title="Clean"))
        assert [p.name for p in notes_dir.iterdir() if p.suffix == ".tmp"] == []

    def test_failed_write_leaves_the_previous_version_intact(self, notes_dir) -> None:
        note = Note(title="original")
        FileManager.save_note(note)

        note.title = "replacement"
        with (
            mock.patch("os.replace", side_effect=OSError("disk full")),
            pytest.raises(StorageError),
        ):
            FileManager.save_note(note)

        # The on-disk copy is still the complete previous version.
        reloaded = FileManager.load_by_id(note.id)
        assert reloaded is not None
        assert reloaded.title == "original"

    def test_failed_write_cleans_up_its_temp_file(self, notes_dir) -> None:
        note = Note(title="original")
        FileManager.save_note(note)
        with (
            mock.patch("os.replace", side_effect=OSError("disk full")),
            pytest.raises(StorageError),
        ):
            FileManager.save_note(note)
        assert [p.name for p in notes_dir.iterdir() if p.name.endswith(".tmp")] == []

    def test_save_raises_storage_error_not_oserror(self, notes_dir) -> None:
        with (
            mock.patch("tempfile.mkstemp", side_effect=OSError("no space")),
            pytest.raises(StorageError),
        ):
            FileManager.save_note(Note())


class TestCorruptionHandling:
    def test_invalid_json_is_skipped_not_fatal(self, notes_dir) -> None:
        (notes_dir / "corrupt.json").write_text("{invalid json", encoding="utf-8")
        FileManager.save_note(Note(title="Good"))

        notes = FileManager.load_all()
        assert [n.title for n in notes] == ["Good"]

    def test_json_that_is_not_an_object_is_skipped(self, notes_dir) -> None:
        (notes_dir / "list.json").write_text("[1, 2, 3]", encoding="utf-8")
        assert FileManager.load_all() == []

    def test_undecodable_bytes_are_skipped(self, notes_dir) -> None:
        (notes_dir / "binary.json").write_bytes(b"\xff\xfe\x00\x01")
        assert FileManager.load_all() == []

    def test_empty_file_is_skipped(self, notes_dir) -> None:
        (notes_dir / "empty.json").write_text("", encoding="utf-8")
        assert FileManager.load_all() == []

    def test_load_by_id_returns_none_for_corrupt_file(self, notes_dir) -> None:
        (notes_dir / "abcd1234.json").write_text("nope", encoding="utf-8")
        assert FileManager.load_by_id("abcd1234") is None

    def test_a_note_whose_id_disagrees_with_its_filename_still_loads(self, notes_dir) -> None:
        payload = json.dumps({"id": "realid00", "title": "Mismatched"})
        (notes_dir / "otherid0.json").write_text(payload, encoding="utf-8")
        notes = FileManager.load_all()
        assert len(notes) == 1
        assert notes[0].id == "realid00"


class TestSearch:
    @pytest.fixture(autouse=True)
    def _seed(self):
        FileManager.save_note(Note(title="Python Notes", content="stuff"))
        FileManager.save_note(Note(title="JavaScript Notes", content="other stuff"))
        FileManager.save_note(Note(title="Recipes", content="contains python keyword"))

    def test_search_matches_title(self) -> None:
        results = FileManager.search("javascript")
        assert [n.title for n in results] == ["JavaScript Notes"]

    def test_search_matches_content(self) -> None:
        results = FileManager.search("keyword")
        assert [n.title for n in results] == ["Recipes"]

    def test_search_spans_title_and_content(self) -> None:
        assert len(FileManager.search("python")) == 2

    def test_search_is_case_insensitive(self) -> None:
        assert len(FileManager.search("PYTHON")) == 2

    def test_blank_search_returns_everything(self) -> None:
        assert len(FileManager.search("   ")) == 3

    def test_no_match_returns_empty(self) -> None:
        assert FileManager.search("zzzz") == []


class TestFilterAndSort:
    def test_filter_does_not_mutate_its_input(self) -> None:
        notes = [Note(title="a"), Note(title="b")]
        filter_notes(notes, "a")
        assert len(notes) == 2

    def test_unordered_notes_sort_by_recency(self) -> None:
        old = Note(title="old", updated_at="2020-01-01T00:00:00+00:00")
        new = Note(title="new", updated_at="2030-01-01T00:00:00+00:00")
        assert [n.title for n in sort_for_display([old, new])] == ["new", "old"]

    def test_explicit_order_wins_over_recency(self) -> None:
        first = Note(title="first", order=1, updated_at="2020-01-01T00:00:00+00:00")
        second = Note(title="second", order=2, updated_at="2030-01-01T00:00:00+00:00")
        assert [n.title for n in sort_for_display([second, first])] == ["first", "second"]

    def test_recency_breaks_ties_within_an_order_group(self) -> None:
        old = Note(title="old", order=1, updated_at="2020-01-01T00:00:00+00:00")
        new = Note(title="new", order=1, updated_at="2030-01-01T00:00:00+00:00")
        assert [n.title for n in sort_for_display([old, new])] == ["new", "old"]

    def test_load_all_returns_display_order(self) -> None:
        FileManager.save_note(Note(title="third", order=3))
        FileManager.save_note(Note(title="first", order=1))
        FileManager.save_note(Note(title="second", order=2))
        assert [n.title for n in FileManager.load_all()] == ["first", "second", "third"]


class TestDirectory:
    def test_directory_is_created_on_demand(self, tmp_path) -> None:
        from notsucky.utils import paths

        target = tmp_path / "fresh" / "notes"
        paths.set_notes_dir(target)
        assert FileManager.directory() == target
        assert target.is_dir()

    def test_unlistable_directory_yields_no_notes(self) -> None:
        with mock.patch.object(os, "listdir", side_effect=OSError("denied")), mock.patch(
            "pathlib.Path.glob", side_effect=OSError("denied")
        ):
            assert FileManager.load_all() == []
