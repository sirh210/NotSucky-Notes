"""Tests for tags: normalization, storage, filtering, and counting."""

from __future__ import annotations

import json

import pytest

from notsucky.models.note import Note, normalize_tag, normalize_tags
from notsucky.services.file_manager import FileManager, all_tags, filter_notes, tag_counts
from notsucky.services.note_service import NoteService
from notsucky.utils.constants import MAX_TAG_LENGTH, MAX_TAGS_PER_NOTE


class TestNormalizeTag:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Work", "work"),
            ("  spaced  ", "spaced"),
            ("Multi   Word", "multi word"),
            ("UPPER", "upper"),
            ("with,comma", "with comma"),
            ("tab\there", "tab here"),
            ("new\nline", "new line"),
        ],
    )
    def test_canonical_forms(self, raw, expected) -> None:
        assert normalize_tag(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", ",", None, 42, [], {}])
    def test_unusable_values_are_rejected(self, raw) -> None:
        assert normalize_tag(raw) is None

    def test_a_long_tag_is_shortened(self) -> None:
        assert len(normalize_tag("x" * 200)) == MAX_TAG_LENGTH


class TestNormalizeTags:
    def test_duplicates_collapse_case_insensitively(self) -> None:
        assert normalize_tags(["Work", "work", "  WORK "]) == ["work"]

    def test_order_is_preserved(self) -> None:
        assert normalize_tags(["zebra", "apple", "mango"]) == ["zebra", "apple", "mango"]

    def test_blanks_are_dropped(self) -> None:
        assert normalize_tags(["ok", "", "   ", None]) == ["ok"]

    def test_a_bare_string_is_accepted(self) -> None:
        assert normalize_tags("solo") == ["solo"]

    @pytest.mark.parametrize("raw", [None, 42, {"a": 1}])
    def test_junk_becomes_empty(self, raw) -> None:
        assert normalize_tags(raw) == []

    def test_loading_never_drops_tags_over_the_cap(self) -> None:
        """The cap governs new input; a file that already holds more keeps
        them, because loading must not quietly discard data."""
        many = [f"tag{i}" for i in range(MAX_TAGS_PER_NOTE + 15)]
        assert len(normalize_tags(many)) == MAX_TAGS_PER_NOTE + 15


class TestNoteTags:
    def test_tags_default_to_empty(self) -> None:
        assert Note().tags == []

    def test_tags_are_normalized_on_construction(self) -> None:
        assert Note(tags=["Work", "work", " Home "]).tags == ["work", "home"]

    def test_tags_survive_a_round_trip(self) -> None:
        original = Note(title="T", tags=["alpha", "beta"])
        assert Note.from_json(original.to_json()).tags == ["alpha", "beta"]

    def test_a_file_without_tags_still_loads(self, notes_dir) -> None:
        (notes_dir / "old00001.json").write_text(
            json.dumps({"id": "old00001", "title": "Legacy"}), encoding="utf-8"
        )
        assert FileManager.load_by_id("old00001").tags == []

    def test_junk_tags_in_a_file_are_repaired(self, notes_dir) -> None:
        (notes_dir / "junk0001.json").write_text(
            json.dumps({"id": "junk0001", "tags": ["ok", 5, None, "", "OK"]}),
            encoding="utf-8",
        )
        assert FileManager.load_by_id("junk0001").tags == ["ok"]

    def test_an_oversized_tag_list_in_a_file_is_kept(self, notes_dir) -> None:
        many = [f"tag{i}" for i in range(40)]
        (notes_dir / "many0001.json").write_text(
            json.dumps({"id": "many0001", "tags": many}), encoding="utf-8"
        )
        assert len(FileManager.load_by_id("many0001").tags) == 40


class TestTagService:
    def test_set_tags_persists(self, notes_dir) -> None:
        note = NoteService.create(title="T")
        assert NoteService.set_tags(note, ["Work", "urgent"]) is True
        assert FileManager.load_by_id(note.id).tags == ["work", "urgent"]

    def test_set_tags_accepts_a_comma_string(self, notes_dir) -> None:
        note = NoteService.create(title="T")
        NoteService.set_tags(note, "work, home ,  urgent")
        assert note.tags == ["work", "home", "urgent"]

    def test_setting_the_same_tags_is_a_no_op(self, notes_dir) -> None:
        note = NoteService.create(title="T")
        NoteService.set_tags(note, ["a"])
        before = note.updated_at
        assert NoteService.set_tags(note, ["A"]) is False
        assert note.updated_at == before

    def test_new_input_is_capped(self, notes_dir) -> None:
        note = NoteService.create(title="T")
        NoteService.set_tags(note, [f"tag{i}" for i in range(MAX_TAGS_PER_NOTE + 10)])
        assert len(note.tags) == MAX_TAGS_PER_NOTE

    def test_add_tag(self, notes_dir) -> None:
        note = NoteService.create(title="T")
        assert NoteService.add_tag(note, "Work") is True
        assert note.tags == ["work"]
        assert NoteService.add_tag(note, "work") is False

    def test_add_tag_refuses_junk(self, notes_dir) -> None:
        note = NoteService.create(title="T")
        assert NoteService.add_tag(note, "  ") is False
        assert note.tags == []

    def test_add_tag_stops_at_the_cap(self, notes_dir) -> None:
        note = NoteService.create(title="T")
        NoteService.set_tags(note, [f"t{i}" for i in range(MAX_TAGS_PER_NOTE)])
        assert NoteService.add_tag(note, "one-more") is False

    def test_remove_tag(self, notes_dir) -> None:
        note = NoteService.create(title="T")
        NoteService.set_tags(note, ["keep", "drop"])
        assert NoteService.remove_tag(note, "DROP") is True
        assert FileManager.load_by_id(note.id).tags == ["keep"]

    def test_remove_absent_tag_is_a_no_op(self, notes_dir) -> None:
        note = NoteService.create(title="T")
        assert NoteService.remove_tag(note, "nope") is False

    def test_tagging_does_not_disturb_the_content(self, notes_dir) -> None:
        note = NoteService.create(title="T", content="precious")
        NoteService.set_tags(note, ["x"])
        assert FileManager.load_by_id(note.id).content == "precious"


class TestFilterByTag:
    @pytest.fixture()
    def seeded(self, notes_dir):
        a = NoteService.create(title="Alpha", content="one")
        b = NoteService.create(title="Beta", content="two")
        c = NoteService.create(title="Gamma", content="three")
        NoteService.set_tags(a, ["work", "urgent"])
        NoteService.set_tags(b, ["work"])
        NoteService.set_tags(c, ["home"])
        return FileManager.load_all()

    def test_one_tag_narrows_the_list(self, seeded) -> None:
        titles = {n.title for n in filter_notes(seeded, "", ["work"])}
        assert titles == {"Alpha", "Beta"}

    def test_two_tags_are_combined_with_and(self, seeded) -> None:
        titles = {n.title for n in filter_notes(seeded, "", ["work", "urgent"])}
        assert titles == {"Alpha"}

    def test_tag_matching_is_case_insensitive(self, seeded) -> None:
        assert len(filter_notes(seeded, "", ["WORK"])) == 2

    def test_no_tags_means_no_tag_filtering(self, seeded) -> None:
        assert len(filter_notes(seeded, "", [])) == 3

    def test_an_unknown_tag_matches_nothing(self, seeded) -> None:
        assert filter_notes(seeded, "", ["nonexistent"]) == []

    def test_text_and_tags_combine(self, seeded) -> None:
        titles = {n.title for n in filter_notes(seeded, "alpha", ["work"])}
        assert titles == {"Alpha"}

    def test_text_search_also_matches_a_tag(self, seeded) -> None:
        titles = {n.title for n in filter_notes(seeded, "urgent")}
        assert titles == {"Alpha"}

    def test_filtering_does_not_mutate_the_input(self, seeded) -> None:
        filter_notes(seeded, "", ["work"])
        assert len(seeded) == 3


class TestTagInventory:
    @pytest.fixture()
    def seeded(self, notes_dir):
        for tags in (["work", "urgent"], ["work"], ["work", "home"], ["home"]):
            note = NoteService.create(title="n")
            NoteService.set_tags(note, tags)
        return FileManager.load_all()

    def test_counts_are_accurate(self, seeded) -> None:
        assert tag_counts(seeded) == {"work": 3, "urgent": 1, "home": 2}

    def test_most_used_comes_first(self, seeded) -> None:
        assert all_tags(seeded)[:2] == ["work", "home"]

    def test_ties_are_alphabetical(self, notes_dir) -> None:
        note = NoteService.create(title="n")
        NoteService.set_tags(note, ["zebra", "apple"])
        assert all_tags(FileManager.load_all()) == ["apple", "zebra"]

    def test_no_tags_gives_an_empty_inventory(self, notes_dir) -> None:
        NoteService.create(title="untagged")
        assert all_tags(FileManager.load_all()) == []
        assert tag_counts(FileManager.load_all()) == {}


class TestTagExport:
    def test_tags_appear_in_the_markdown_front_matter(self, notes_dir) -> None:
        from notsucky.services import export

        note = NoteService.create(title="T")
        NoteService.set_tags(note, ["work", "urgent"])
        rendered = export.render(FileManager.load_by_id(note.id), "md")
        assert "tags: work, urgent" in rendered
