"""Tests for the Note data model."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from notsucky.models.note import ID_LENGTH, Note, is_valid_id, new_id, utc_now
from notsucky.utils.constants import (
    DEFAULT_NOTE_HEIGHT,
    DEFAULT_NOTE_WIDTH,
    MAX_CONTENT_LENGTH,
    MIN_NOTE_HEIGHT,
    MIN_NOTE_WIDTH,
)


class TestNoteCreation:
    def test_default_id_is_generated(self) -> None:
        assert len(Note().id) == ID_LENGTH

    def test_ids_are_unique(self) -> None:
        assert len({new_id() for _ in range(500)}) == 500

    def test_text_fields_default_to_empty(self) -> None:
        note = Note()
        assert note.title == ""
        assert note.content == ""

    def test_color_defaults_to_yellow(self) -> None:
        assert Note().color == "Yellow"

    def test_minimized_defaults_to_false(self) -> None:
        assert Note().minimized is False

    def test_default_size_is_applied(self) -> None:
        note = Note()
        assert (note.width, note.height) == (DEFAULT_NOTE_WIDTH, DEFAULT_NOTE_HEIGHT)

    def test_timestamps_are_timezone_aware(self) -> None:
        note = Note()
        assert datetime.fromisoformat(note.created_at).tzinfo is not None
        assert datetime.fromisoformat(note.updated_at).tzinfo is not None

    def test_timestamps_are_current(self) -> None:
        before = utc_now()
        note = Note()
        assert before <= note.created_at <= utc_now()

    def test_touch_advances_updated_at(self) -> None:
        note = Note(updated_at="2000-01-01T00:00:00+00:00")
        note.touch()
        assert note.updated_at > "2000-01-01T00:00:00+00:00"


class TestNoteValidation:
    @pytest.mark.parametrize(
        "value", ["../../etc/passwd", "a/b", "a\\b", "", "x" * 65, None, 42, "a.b"]
    )
    def test_unsafe_ids_are_rejected(self, value) -> None:
        assert is_valid_id(value) is False

    @pytest.mark.parametrize("value", ["abc12345", "A-b_9", "x"])
    def test_safe_ids_are_accepted(self, value) -> None:
        assert is_valid_id(value) is True

    def test_traversal_id_is_replaced_at_construction(self) -> None:
        note = Note(id="../../evil")
        assert note.id != "../../evil"
        assert is_valid_id(note.id)

    def test_unknown_color_falls_back_to_default(self) -> None:
        assert Note(color="Chartreuse").color == "Yellow"

    def test_an_oversized_title_is_preserved(self) -> None:
        """Truncating on load is written back by the next save as a deletion."""
        assert len(Note(title="x" * 5000).title) == 5000

    def test_oversized_content_is_preserved(self) -> None:
        oversized = MAX_CONTENT_LENGTH + 10
        assert len(Note(content="x" * oversized).content) == oversized

    def test_undersized_geometry_is_raised_to_minimum(self) -> None:
        note = Note(width=10, height=10)
        assert (note.width, note.height) == (MIN_NOTE_WIDTH, MIN_NOTE_HEIGHT)


class TestNoteSerialization:
    def test_to_dict_is_plain_and_complete(self) -> None:
        data = Note(title="Hello", content="World").to_dict()
        assert isinstance(data, dict)
        assert data["title"] == "Hello"
        assert data["content"] == "World"
        assert {"id", "color", "x", "y", "width", "height", "order"} <= data.keys()

    def test_from_dict_restores_all_fields(self) -> None:
        note = Note.from_dict(
            {
                "id": "abc12345",
                "title": "Test Note",
                "content": "Some content here",
                "color": "Blue",
                "x": 100,
                "y": 200,
                "width": 400,
                "height": 300,
                "minimized": True,
                "order": 7,
            }
        )
        assert note.id == "abc12345"
        assert note.title == "Test Note"
        assert note.content == "Some content here"
        assert note.color == "Blue"
        assert (note.x, note.y) == (100, 200)
        assert (note.width, note.height) == (400, 300)
        assert note.minimized is True
        assert note.order == 7

    def test_round_trip_preserves_everything(self) -> None:
        original = Note(title="Round Trip", content="Body", color="Pink", x=5, y=6, order=3)
        restored = Note.from_json(original.to_json())
        assert restored.to_dict() == original.to_dict()

    def test_unicode_survives_round_trip(self) -> None:
        original = Note(title="日本語 📝", content="Ünïcødé\nlines")
        restored = Note.from_json(original.to_json())
        assert restored.title == original.title
        assert restored.content == original.content

    def test_json_is_human_readable(self) -> None:
        raw = Note(title="é").to_json()
        assert "\n" in raw
        assert "é" in raw  # ensure_ascii is off


class TestNoteRepair:
    """A hand-edited or partially written file must still load."""

    def test_missing_keys_use_defaults(self) -> None:
        note = Note.from_dict({})
        assert note.title == ""
        assert note.color == "Yellow"
        assert is_valid_id(note.id)

    def test_wrong_types_are_coerced(self) -> None:
        note = Note.from_dict(
            {"title": 123, "content": None, "x": "left", "width": "wide", "order": None}
        )
        assert note.title == ""
        assert note.content == ""
        assert note.x is None
        assert note.width == DEFAULT_NOTE_WIDTH
        assert note.order == 0

    def test_unknown_keys_are_ignored(self) -> None:
        note = Note.from_dict({"title": "Keep", "bogus": "drop", "__class__": "evil"})
        assert note.title == "Keep"
        assert not hasattr(note, "bogus")

    def test_float_coordinates_are_accepted(self) -> None:
        assert Note.from_dict({"x": 10.0, "y": 20.0}).x == 10

    def test_non_object_json_raises(self) -> None:
        with pytest.raises(ValueError):
            Note.from_dict([1, 2, 3])
        with pytest.raises(ValueError):
            Note.from_json(json.dumps("just a string"))

    def test_updated_at_defaults_to_created_at(self) -> None:
        note = Note.from_dict({"created_at": "2020-01-01T00:00:00+00:00"})
        assert note.updated_at == "2020-01-01T00:00:00+00:00"


class TestNotePaths:
    def test_file_path_is_inside_the_active_notes_dir(self, notes_dir) -> None:
        note = Note(id="test1234")
        assert note.file_path == notes_dir / "test1234.json"

    def test_file_path_follows_a_later_override(self, tmp_path) -> None:
        from notsucky.utils import paths

        note = Note(id="test1234")
        moved = tmp_path / "elsewhere"
        paths.set_notes_dir(moved)
        assert note.file_path.parent == moved
