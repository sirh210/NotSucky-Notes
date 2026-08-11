"""Tests for NoteService business logic."""

from __future__ import annotations

import pytest

from notsucky.models.note import Note
from notsucky.services.file_manager import FileManager, sort_for_display
from notsucky.services.note_service import NoteService
from notsucky.utils.constants import MIN_NOTE_HEIGHT, MIN_NOTE_WIDTH


class TestCreate:
    def test_create_persists_immediately(self) -> None:
        note = NoteService.create(title="Test", content="Content")
        assert note.title == "Test"
        assert note.content == "Content"
        assert FileManager.load_by_id(note.id) is not None

    def test_untitled_notes_get_a_placeholder_title(self) -> None:
        assert NoteService.create().title.startswith("Note ")

    def test_unknown_color_falls_back(self) -> None:
        assert NoteService.create(color="Neon").color == "Yellow"

    def test_created_and_updated_start_equal(self) -> None:
        note = NoteService.create()
        assert note.created_at == note.updated_at


class TestFieldUpdates:
    def test_update_title_persists(self) -> None:
        note = NoteService.create(title="Old Title")
        assert NoteService.update_title(note, "New Title") is True
        assert note.title == "New Title"
        assert FileManager.load_by_id(note.id).title == "New Title"

    def test_update_title_is_a_no_op_when_unchanged(self) -> None:
        note = NoteService.create(title="Same")
        before = note.updated_at
        assert NoteService.update_title(note, "Same") is False
        assert note.updated_at == before

    def test_update_content_strips_trailing_newlines(self) -> None:
        note = NoteService.create(content="Original")
        NoteService.update_content(note, "Updated content\nwith newlines\n\n")
        assert note.content == "Updated content\nwith newlines"

    def test_update_content_keeps_interior_newlines(self) -> None:
        note = NoteService.create()
        NoteService.update_content(note, "a\n\nb")
        assert FileManager.load_by_id(note.id).content == "a\n\nb"

    def test_update_content_is_a_no_op_when_unchanged(self) -> None:
        note = NoteService.create(content="Same")
        assert NoteService.update_content(note, "Same") is False

    def test_updates_advance_the_timestamp(self) -> None:
        note = NoteService.create(title="a")
        note.updated_at = "2000-01-01T00:00:00+00:00"
        NoteService.update_title(note, "b")
        assert note.updated_at > "2000-01-01T00:00:00+00:00"


class TestColor:
    def test_change_color_persists(self) -> None:
        note = NoteService.create(color="Yellow")
        assert NoteService.change_color(note, "Blue") is True
        assert FileManager.load_by_id(note.id).color == "Blue"

    def test_change_to_same_color_is_a_no_op(self) -> None:
        note = NoteService.create(color="Green")
        before = note.updated_at
        assert NoteService.change_color(note, "Green") is False
        assert note.updated_at == before

    def test_unknown_color_is_rejected(self) -> None:
        note = NoteService.create(color="Green")
        assert NoteService.change_color(note, "Rainbow") is False
        assert note.color == "Green"


class TestGeometry:
    def test_geometry_is_persisted(self) -> None:
        note = NoteService.create()
        assert NoteService.update_geometry(note, 10, 20, 400, 350) is True

        loaded = FileManager.load_by_id(note.id)
        assert (loaded.x, loaded.y, loaded.width, loaded.height) == (10, 20, 400, 350)

    def test_geometry_does_not_count_as_an_edit(self) -> None:
        note = NoteService.create()
        before = note.updated_at
        NoteService.update_geometry(note, 5, 5)
        assert note.updated_at == before

    def test_repeated_geometry_is_a_no_op(self) -> None:
        note = NoteService.create()
        NoteService.update_geometry(note, 1, 2, 300, 300)
        assert NoteService.update_geometry(note, 1, 2, 300, 300) is False

    def test_tiny_sizes_are_clamped(self) -> None:
        note = NoteService.create()
        NoteService.update_geometry(note, 0, 0, 1, 1)
        assert (note.width, note.height) == (MIN_NOTE_WIDTH, MIN_NOTE_HEIGHT)

    def test_negative_positions_are_allowed(self) -> None:
        """Multi-monitor setups have legitimately negative coordinates."""
        note = NoteService.create()
        NoteService.update_geometry(note, -1200, 40)
        assert note.x == -1200


class TestMinimize:
    def test_toggle_round_trips(self) -> None:
        note = NoteService.create()
        assert note.minimized is False
        assert NoteService.toggle_minimize(note) is True
        assert FileManager.load_by_id(note.id).minimized is True
        assert NoteService.toggle_minimize(note) is False
        assert FileManager.load_by_id(note.id).minimized is False

    def test_set_minimized_is_idempotent(self) -> None:
        note = NoteService.create()
        assert NoteService.set_minimized(note, True) is True
        assert NoteService.set_minimized(note, True) is False


class TestReorder:
    @pytest.fixture()
    def three(self):
        notes = [NoteService.create(title=name) for name in ("a", "b", "c")]
        for position, note in enumerate(notes, start=1):
            note.order = position
            FileManager.save_note(note)
        return notes

    def test_moving_last_to_first(self, three) -> None:
        a, _b, c = three
        assert NoteService.reorder(three, c.id, a.id) is True
        assert [n.title for n in FileManager.load_all()] == ["c", "a", "b"]

    def test_moving_first_to_last(self, three) -> None:
        a, _b, c = three
        NoteService.reorder(three, a.id, c.id)
        assert [n.title for n in FileManager.load_all()] == ["b", "c", "a"]

    def test_reorder_onto_self_is_a_no_op(self, three) -> None:
        a = three[0]
        assert NoteService.reorder(three, a.id, a.id) is False

    def test_unknown_ids_are_ignored(self, three) -> None:
        assert NoteService.reorder(three, "missing0", three[0].id) is False

    def test_positions_are_dense_after_reorder(self, three) -> None:
        NoteService.reorder(three, three[2].id, three[0].id)
        assert [n.order for n in FileManager.load_all()] == [1, 2, 3]

    def test_previously_unordered_notes_get_positions(self) -> None:
        notes = [NoteService.create(title=name) for name in ("x", "y")]
        assert all(n.order == 0 for n in notes)
        NoteService.reorder(sort_for_display(notes), notes[1].id, notes[0].id)
        assert sorted(n.order for n in FileManager.load_all()) == [1, 2]


class TestDelete:
    def test_delete_removes_the_file(self) -> None:
        note = NoteService.create(title="To Delete")
        assert NoteService.delete(note) is not None
        assert FileManager.load_by_id(note.id) is None

    def test_deleting_twice_returns_no_second_token(self) -> None:
        note = NoteService.create()
        NoteService.delete(note)
        assert NoteService.delete(note) is None

    def test_delete_is_undoable(self) -> None:
        note = NoteService.create(title="Oops")
        token = NoteService.delete(note)

        assert NoteService.undo_delete(token) is not None
        assert FileManager.load_by_id(note.id).title == "Oops"

    def test_deleting_one_note_leaves_the_others(self) -> None:
        keep = NoteService.create(title="keep")
        drop = NoteService.create(title="drop")
        NoteService.delete(drop)
        assert [n.id for n in FileManager.load_all()] == [keep.id]


class TestLimits:
    """The service persists what it is given. Growth is bounded in the
    editor, because a limit enforced down here silently deletes text that
    already existed."""

    def test_a_long_title_is_persisted_in_full(self) -> None:
        note = NoteService.create()
        NoteService.update_title(note, "x" * 10_000)
        assert len(FileManager.load_by_id(note.id).title) == 10_000

    def test_long_content_is_persisted_in_full(self) -> None:
        note = Note()
        FileManager.save_note(note)
        NoteService.update_content(note, "y" * 2_000_000)
        assert len(note.content) == 2_000_000
        assert len(FileManager.load_by_id(note.id).content) == 2_000_000
