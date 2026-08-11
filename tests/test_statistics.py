"""Tests for the statistics computation."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from notsucky.models.note import Note
from notsucky.services import statistics
from notsucky.services.note_service import NoteService

TODAY = date(2026, 8, 11)


def at(day: date, hour: int = 12) -> str:
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc).isoformat()


def note(**kwargs) -> Note:
    kwargs.setdefault("created_at", at(TODAY))
    kwargs.setdefault("updated_at", at(TODAY))
    return Note(**kwargs)


class TestEmptyStore:
    def test_no_notes_gives_zeroes(self) -> None:
        stats = statistics.compute([], today=TODAY)
        assert stats.total_notes == 0
        assert stats.total_words == 0
        assert stats.longest_note is None
        assert stats.most_used_color is None

    def test_the_activity_window_is_still_full(self) -> None:
        stats = statistics.compute([], days=14, today=TODAY)
        assert len(stats.activity) == 14
        assert all(created == 0 and updated == 0 for _d, created, updated in stats.activity)

    def test_the_peak_is_zero_not_an_error(self) -> None:
        assert statistics.compute([], today=TODAY).peak_activity == 0

    def test_there_is_no_busiest_day(self) -> None:
        assert statistics.compute([], today=TODAY).busiest_day is None


class TestTotals:
    @pytest.fixture()
    def stats(self):
        return statistics.compute(
            [
                note(title="a", content="one two three"),
                note(title="b", content="four five"),
                note(title="c", content=""),
            ],
            today=TODAY,
        )

    def test_note_count(self, stats) -> None:
        assert stats.total_notes == 3

    def test_word_and_character_counts(self, stats) -> None:
        assert stats.total_words == 5
        assert stats.total_characters == len("one two three") + len("four five")

    def test_empty_notes_are_counted(self, stats) -> None:
        assert stats.empty_notes == 1

    def test_average_length_is_rounded(self, stats) -> None:
        assert stats.average_characters == round(stats.total_characters / 3)

    def test_whitespace_only_counts_as_empty(self) -> None:
        assert statistics.compute([note(content="   \n ")], today=TODAY).empty_notes == 1

    def test_minimized_notes_are_counted(self) -> None:
        stats = statistics.compute(
            [note(minimized=True), note(minimized=False)], today=TODAY
        )
        assert stats.minimized_notes == 1

    def test_trash_and_backup_counts_pass_through(self) -> None:
        stats = statistics.compute([], trash_count=4, backup_count=2, today=TODAY)
        assert (stats.trash_count, stats.backup_count) == (4, 2)


class TestSuperlatives:
    def test_the_longest_note_wins(self) -> None:
        stats = statistics.compute(
            [note(title="short", content="ab"), note(title="long", content="abcdef")],
            today=TODAY,
        )
        assert stats.longest_note.title == "long"

    def test_oldest_and_newest_by_creation(self) -> None:
        old = note(title="old", created_at=at(date(2020, 1, 1)))
        new = note(title="new", created_at=at(date(2026, 1, 1)))
        stats = statistics.compute([new, old], today=TODAY)
        assert stats.oldest_note.title == "old"
        assert stats.newest_note.title == "new"

    def test_a_single_note_is_both(self) -> None:
        stats = statistics.compute([note(title="only")], today=TODAY)
        assert stats.oldest_note.title == stats.newest_note.title == "only"


class TestColourBreakdown:
    def test_counts_are_ranked(self) -> None:
        notes = [note(color="Blue"), note(color="Blue"), note(color="Pink")]
        stats = statistics.compute(notes, today=TODAY)
        assert stats.colors == [("Blue", 2), ("Pink", 1)]

    def test_most_used_colour(self) -> None:
        notes = [note(color="Green"), note(color="Green"), note(color="Yellow")]
        assert statistics.compute(notes, today=TODAY).most_used_color == "Green"

    def test_ties_break_alphabetically(self) -> None:
        notes = [note(color="Purple"), note(color="Blue")]
        assert statistics.compute(notes, today=TODAY).colors == [("Blue", 1), ("Purple", 1)]

    def test_unused_colours_are_absent(self) -> None:
        stats = statistics.compute([note(color="Blue")], today=TODAY)
        assert [name for name, _ in stats.colors] == ["Blue"]


class TestTagBreakdown:
    def test_tags_are_ranked_and_capped(self) -> None:
        notes = [note(tags=["a", "b"]), note(tags=["a"]), note(tags=["a", "c"])]
        stats = statistics.compute(notes, today=TODAY)
        assert stats.tags[0] == ("a", 3)
        assert len(stats.tags) <= statistics.TOP_TAGS

    def test_only_the_top_tags_are_kept(self) -> None:
        notes = [note(tags=[f"t{i}" for i in range(20)])]
        assert len(statistics.compute(notes, today=TODAY).tags) == statistics.TOP_TAGS

    def test_distinct_and_untagged_counts(self) -> None:
        stats = statistics.compute(
            [note(tags=["x", "y"]), note(tags=[]), note(tags=[])], today=TODAY
        )
        assert stats.distinct_tags == 2
        assert stats.untagged_notes == 2


class TestActivity:
    def test_the_window_has_one_row_per_day(self) -> None:
        stats = statistics.compute([note()], days=7, today=TODAY)
        assert len(stats.activity) == 7

    def test_the_window_ends_today(self) -> None:
        stats = statistics.compute([note()], days=7, today=TODAY)
        assert stats.activity[-1][0] == TODAY

    def test_the_window_is_chronological(self) -> None:
        days = [day for day, _c, _u in statistics.compute([], days=5, today=TODAY).activity]
        assert days == sorted(days)

    def test_edits_land_on_the_right_day(self) -> None:
        yesterday = TODAY - timedelta(days=1)
        stats = statistics.compute(
            [note(updated_at=at(yesterday)), note(updated_at=at(TODAY))],
            days=7,
            today=TODAY,
        )
        by_day = {day: updated for day, _c, updated in stats.activity}
        assert by_day[yesterday] == 1
        assert by_day[TODAY] == 1

    def test_creations_are_tracked_separately(self) -> None:
        stats = statistics.compute(
            [note(created_at=at(TODAY), updated_at=at(TODAY))], days=3, today=TODAY
        )
        created = {day: c for day, c, _u in stats.activity}
        assert created[TODAY] == 1

    def test_notes_outside_the_window_are_excluded(self) -> None:
        old = note(created_at=at(date(2020, 1, 1)), updated_at=at(date(2020, 1, 1)))
        stats = statistics.compute([old], days=7, today=TODAY)
        assert stats.peak_activity == 0

    def test_the_peak_and_busiest_day_agree(self) -> None:
        stats = statistics.compute(
            [note(updated_at=at(TODAY)), note(updated_at=at(TODAY))],
            days=7,
            today=TODAY,
        )
        assert stats.peak_activity == 2
        assert stats.busiest_day == (TODAY, 2)

    def test_naive_v1_timestamps_still_bucket(self) -> None:
        """1.0 wrote naive local timestamps; they must not be dropped."""
        naive = note(updated_at="2026-08-11T09:30:00")
        stats = statistics.compute([naive], days=3, today=TODAY)
        assert stats.peak_activity == 1

    def test_an_unparseable_timestamp_is_skipped_not_fatal(self) -> None:
        stats = statistics.compute([note(updated_at="not a date")], days=3, today=TODAY)
        assert stats.peak_activity == 0


class TestReport:
    def test_the_report_covers_the_headline_figures(self, notes_dir) -> None:
        NoteService.create(title="Alpha", content="one two three")
        text = statistics.format_report(statistics.collect())
        assert "total" in text
        assert "words" in text
        assert "Longest note" in text

    def test_the_report_lists_colours_and_tags(self, notes_dir) -> None:
        note_ = NoteService.create(title="A", content="x", color="Blue")
        NoteService.set_tags(note_, ["work"])
        text = statistics.format_report(statistics.collect())
        assert "Blue" in text
        assert "work" in text

    def test_the_report_works_with_no_notes(self, notes_dir) -> None:
        text = statistics.format_report(statistics.collect())
        assert "total              : 0" in text

    def test_the_report_leaks_no_note_content(self, notes_dir) -> None:
        """It is a summary, and safe to paste."""
        NoteService.create(title="Bank", content="account 12345678 sort 00-00-00")
        text = statistics.format_report(statistics.collect())
        assert "12345678" not in text

    def test_collect_reads_the_store(self, notes_dir) -> None:
        NoteService.create(title="A")
        NoteService.delete(NoteService.create(title="B"))
        stats = statistics.collect()
        assert stats.total_notes == 1
        assert stats.trash_count == 1
