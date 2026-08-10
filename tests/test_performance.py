"""Performance guards.

Thresholds are deliberately loose — several times the measured cost on a
modest laptop — so they catch a structural regression (per-widget stylesheets
creeping back, the grid building everything up front, search re-reading the
disk) without failing on a slow CI runner.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6", reason="PySide6 is required for GUI tests")

from notsucky.models.note import Note, new_id
from notsucky.services.file_manager import FileManager, filter_notes
from notsucky.utils.constants import GRID_FIRST_CHUNK
from notsucky.views.card_widget import CardWidget
from notsucky.views.dashboard import DashboardWindow

BODY = "lorem ipsum dolor sit amet consectetur adipiscing elit " * 8


def seed_notes(directory, count: int) -> None:
    """Write ``count`` notes straight to disk, bypassing the service layer."""
    for index in range(count):
        note = Note(id=new_id(), title=f"Note {index}", content=f"{BODY}{index}", order=index + 1)
        (directory / f"{note.id}.json").write_text(note.to_json(), encoding="utf-8")


def elapsed_ms(fn) -> float:
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


class TestGridStreaming:
    """The grid must not build every card before the window can paint."""

    def test_first_paint_builds_only_the_first_chunk(self, qtbot, notes_dir) -> None:
        seed_notes(notes_dir, 300)
        window = DashboardWindow()
        qtbot.addWidget(window)

        assert window._built_cards == GRID_FIRST_CHUNK
        assert len(window._visible_notes) == 300

    def test_the_remaining_cards_stream_in(self, qtbot, notes_dir) -> None:
        seed_notes(notes_dir, 120)
        window = DashboardWindow()
        qtbot.addWidget(window)

        qtbot.waitUntil(lambda: window._built_cards == 120, timeout=5000)
        assert len(window.grid_frame.findChildren(CardWidget)) == 120

    def test_finishing_synchronously_builds_everything(self, qtbot, notes_dir) -> None:
        seed_notes(notes_dir, 150)
        window = DashboardWindow()
        qtbot.addWidget(window)

        window.finish_building_grid()
        assert window._built_cards == 150

    def test_a_small_grid_completes_in_one_pass(self, qtbot, notes_dir) -> None:
        seed_notes(notes_dir, 5)
        window = DashboardWindow()
        qtbot.addWidget(window)

        assert window._built_cards == 5
        assert window._card_timer.isActive() is False

    def test_a_new_rebuild_abandons_the_previous_stream(self, qtbot, notes_dir) -> None:
        seed_notes(notes_dir, 300)
        window = DashboardWindow()
        qtbot.addWidget(window)

        window.search_input.setText("Note 1")
        window._rebuild_grid()

        # Counting is restarted, not continued from the abandoned stream.
        assert window._built_cards <= GRID_FIRST_CHUNK
        window.finish_building_grid()
        assert window._built_cards == len(window._visible_notes)

    def test_cards_are_positioned_in_reading_order(self, qtbot, notes_dir) -> None:
        seed_notes(notes_dir, 60)
        window = DashboardWindow()
        qtbot.addWidget(window)
        window.finish_building_grid()

        columns = window._columns
        for index, note in enumerate(window._visible_notes):
            item = window.grid_layout.itemAtPosition(index // columns, index % columns)
            assert item is not None and item.widget().note.id == note.id


class TestCardCost:
    def test_cards_do_not_carry_their_own_stylesheet(self, qtbot) -> None:
        """Per-widget CSS is re-parsed by Qt for every card; it was 80% of
        the cost of building the grid."""
        card = CardWidget(Note(title="T", content="body"))
        qtbot.addWidget(card)

        assert card.styleSheet() == ""
        for child in card.findChildren(object):
            if hasattr(child, "styleSheet"):
                assert child.styleSheet() == "", child

    def test_building_many_cards_stays_fast(self, qtbot) -> None:
        notes = [Note(title=f"N{i}", content=BODY) for i in range(200)]
        host = CardWidget(Note(title="host"))
        qtbot.addWidget(host)

        cost = elapsed_ms(lambda: [CardWidget(n, host) for n in notes])
        # ~140us each when healthy; 1.5ms each means the CSS regression is back.
        assert cost < 200 * 1.5, f"{cost:.0f}ms for 200 cards"


class TestDataPathCost:
    def test_loading_many_notes_stays_fast(self, notes_dir) -> None:
        seed_notes(notes_dir, 500)
        # Warm the OS cache first: the point is to catch an algorithmic
        # regression, not to measure a cold read of 500 freshly written files
        # past a virus scanner.
        FileManager.load_all()

        cost = elapsed_ms(FileManager.load_all)
        assert cost < 1500, f"load_all took {cost:.0f}ms for 500 notes"

    def test_filtering_is_in_memory_and_cheap(self, notes_dir) -> None:
        seed_notes(notes_dir, 500)
        notes = FileManager.load_all()

        cost = elapsed_ms(lambda: [filter_notes(notes, "Note 4") for _ in range(20)])
        assert cost < 500, f"20 filter passes took {cost:.0f}ms"

    def test_typing_in_the_filter_never_touches_the_disk(self, qtbot, notes_dir) -> None:
        from unittest import mock

        seed_notes(notes_dir, 50)
        window = DashboardWindow()
        qtbot.addWidget(window)

        with mock.patch.object(FileManager, "load_all", return_value=[]) as spy:
            for fragment in ("N", "No", "Not", "Note"):
                window.search_input.setText(fragment)
                window._rebuild_grid()
            assert spy.call_count == 0
