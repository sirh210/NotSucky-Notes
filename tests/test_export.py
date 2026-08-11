"""Tests for search highlighting and note export."""

from __future__ import annotations

import zipfile
from html import escape

import pytest

from notsucky.models.note import Note
from notsucky.services import export
from notsucky.services.note_service import NoteService
from notsucky.utils.highlight import find_matches, highlight, preview_around_match


class TestFindMatches:
    def test_finds_every_occurrence(self) -> None:
        assert find_matches("aXbXc", "x") == [(1, 2), (3, 4)]

    def test_is_case_insensitive(self) -> None:
        assert find_matches("Hello HELLO hello", "hello") == [(0, 5), (6, 11), (12, 17)]

    def test_matches_never_overlap(self) -> None:
        assert find_matches("aaaa", "aa") == [(0, 2), (2, 4)]

    @pytest.mark.parametrize("query", ["", "   ", "\t\n"])
    def test_a_blank_query_matches_nothing(self, query) -> None:
        assert find_matches("anything", query) == []

    def test_empty_text_matches_nothing(self) -> None:
        assert find_matches("", "x") == []

    def test_no_match_returns_empty(self) -> None:
        assert find_matches("abc", "z") == []


class TestHighlight:
    def test_the_match_is_wrapped(self) -> None:
        out = highlight("find the needle here", "needle")
        assert "<span" in out and "needle</span>" in out

    def test_surrounding_text_survives(self) -> None:
        out = highlight("before needle after", "needle")
        assert out.startswith("before ")
        assert out.endswith(" after")

    def test_original_casing_is_preserved(self) -> None:
        assert "NeEdLe</span>" in highlight("a NeEdLe b", "needle")

    def test_note_markup_is_escaped_not_rendered(self) -> None:
        """A note containing HTML must display it, not obey it."""
        out = highlight("<b>bold</b> & <script>alert(1)</script>", "bold")
        assert "<b>" not in out
        assert "&lt;b&gt;" in out
        assert "<script>" not in out
        assert "&amp;" in out

    def test_escaping_still_happens_with_no_match(self) -> None:
        assert highlight("<i>x</i>", "zzz") == escape("<i>x</i>")

    def test_escaping_happens_inside_the_match_too(self) -> None:
        out = highlight("a <tag> b", "<tag>")
        assert "&lt;tag&gt;</span>" in out

    def test_a_blank_query_leaves_plain_escaped_text(self) -> None:
        assert highlight("plain & simple", "") == escape("plain & simple")

    def test_every_occurrence_is_marked(self) -> None:
        assert highlight("x y x y x", "x").count("<span") == 3


class TestPreviewWindow:
    def test_short_text_is_returned_whole(self) -> None:
        assert preview_around_match("short note", "note", 80) == "short note"

    def test_whitespace_is_collapsed(self) -> None:
        assert preview_around_match("a\n\n  b\tc", "", 80) == "a b c"

    def test_a_late_match_is_brought_into_view(self) -> None:
        text = ("filler " * 200) + "TREASURE at the end"
        window = preview_around_match(text, "treasure", 80)
        assert "TREASURE" in window
        assert window.startswith("…")
        assert len(window) <= 82

    def test_an_early_match_keeps_the_natural_start(self) -> None:
        text = "TREASURE " + ("filler " * 200)
        window = preview_around_match(text, "treasure", 80)
        assert window.startswith("TREASURE")
        assert window.endswith("…")

    def test_no_match_falls_back_to_the_opening(self) -> None:
        text = "alpha " * 100
        assert preview_around_match(text, "zzz", 40).startswith("alpha")

    def test_the_window_respects_the_width(self) -> None:
        text = "word " * 500
        assert len(preview_around_match(text, "word", 60)) <= 62


class TestRender:
    def test_markdown_has_front_matter_and_heading(self) -> None:
        out = export.render(Note(title="My Note", content="Body"), "md")
        assert out.startswith("---\n")
        assert "title: My Note" in out
        assert "# My Note" in out
        assert out.rstrip().endswith("Body")

    def test_plain_text_is_underlined(self) -> None:
        out = export.render(Note(title="Hi", content="Body"), "txt")
        assert out.startswith("Hi\n==\n")
        assert "---" not in out

    def test_an_untitled_note_renders(self) -> None:
        assert "Untitled" in export.render(Note(content="x"), "md")

    def test_unicode_survives(self) -> None:
        out = export.render(Note(title="日本語 📝", content="Ünïcødé"), "md")
        assert "日本語 📝" in out and "Ünïcødé" in out

    def test_an_unknown_format_is_refused(self) -> None:
        with pytest.raises(ValueError):
            export.render(Note(), "pdf")


class TestSafeFilename:
    @pytest.mark.parametrize(
        "title", ['a/b\\c:d*e?f"g<h>i|j', "....", "   ", "", "CON", "NUL"]
    )
    def test_hostile_titles_produce_a_usable_name(self, title) -> None:
        name = export.safe_filename(Note(id="abcd1234", title=title), "md")
        assert not set(name) & set('<>:"/\\|?*')
        assert name.endswith(".md")
        assert "abcd1234" in name

    def test_the_id_disambiguates_duplicate_titles(self) -> None:
        a = export.safe_filename(Note(id="aaaa1111", title="Same"), "md")
        b = export.safe_filename(Note(id="bbbb2222", title="Same"), "md")
        assert a != b

    def test_long_titles_are_shortened(self) -> None:
        name = export.safe_filename(Note(id="abcd1234", title="T" * 500), "md")
        assert len(name) < 100


class TestExportToDirectory:
    def test_every_note_becomes_a_file(self, tmp_path, notes_dir) -> None:
        for title in ("one", "two", "three"):
            NoteService.create(title=title, content=f"body of {title}")

        written = export.export_all(tmp_path / "out", "md")
        assert len(written) == 3
        assert all(p.exists() for p in written)

    def test_the_content_is_readable_without_this_app(self, tmp_path, notes_dir) -> None:
        NoteService.create(title="Recipe", content="Mix and bake.")
        written = export.export_all(tmp_path / "out", "md")
        text = written[0].read_text(encoding="utf-8")
        assert "Mix and bake." in text

    def test_the_destination_is_created(self, tmp_path, notes_dir) -> None:
        NoteService.create(title="x")
        target = tmp_path / "deep" / "nested"
        export.export_all(target, "md")
        assert target.is_dir()

    def test_exporting_nothing_is_not_an_error(self, tmp_path, notes_dir) -> None:
        assert export.export_all(tmp_path / "out", "md") == []

    def test_export_does_not_touch_the_notes(self, tmp_path, notes_dir) -> None:
        note = NoteService.create(title="Untouched", content="body")
        before = (notes_dir / f"{note.id}.json").read_bytes()

        export.export_all(tmp_path / "out", "md")
        assert (notes_dir / f"{note.id}.json").read_bytes() == before


class TestExportArchive:
    def test_every_note_is_in_the_zip(self, tmp_path, notes_dir) -> None:
        for title in ("a", "b"):
            NoteService.create(title=title)

        archive = export.export_archive(tmp_path / "out.zip", "md")
        with zipfile.ZipFile(archive) as zf:
            assert len(zf.namelist()) == 2

    def test_no_notes_produces_no_archive(self, tmp_path, notes_dir) -> None:
        assert export.export_archive(tmp_path / "out.zip") is None

    def test_no_partial_file_is_left_behind(self, tmp_path, notes_dir) -> None:
        NoteService.create(title="a")
        export.export_archive(tmp_path / "out.zip")
        assert list(tmp_path.glob("*.part")) == []

    def test_the_default_name_is_dated_and_unique(self) -> None:
        name = export.default_archive_name("md")
        assert name.startswith("notsucky-export-md-")
        assert name.endswith(".zip")
