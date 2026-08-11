"""GUI tests for the dashboard, cards, and note windows.

These need a Qt platform plugin. On a headless machine set
``QT_QPA_PLATFORM=offscreen``; the suite skips itself if Qt cannot start.
"""

from __future__ import annotations

from unittest import mock

import pytest

pytest.importorskip("PySide6", reason="PySide6 is required for GUI tests")

from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QMessageBox

from notsucky.models.note import Note
from notsucky.services.file_manager import FileManager, StorageError
from notsucky.services.note_service import NoteService
from notsucky.utils.constants import NOTE_MIME_TYPE
from notsucky.views.card_widget import CardWidget, format_relative
from notsucky.views.dashboard import DashboardWindow
from notsucky.views.note_widget import NoteWidget


@pytest.fixture()
def dashboard(qtbot):
    window = DashboardWindow()
    qtbot.addWidget(window)
    yield window
    window.close()


def _flush(widget) -> None:
    """Run a widget's pending debounced save immediately."""
    widget._save_timer.stop()
    widget.flush()


class TestCardWidget:
    def test_card_renders_note_fields(self, qtbot) -> None:
        from PySide6.QtWidgets import QLabel

        card = CardWidget(Note(title="My Title", content="Body text"))
        qtbot.addWidget(card)
        texts = [lbl.text() for lbl in card.findChildren(QLabel)]
        assert "My Title" in texts
        assert "Body text" in texts
        assert any("9 chars" in text for text in texts)

    def test_the_card_actually_paints_its_color(self, qtbot) -> None:
        """A QWidget subclass drops its stylesheet background without
        WA_StyledBackground, which renders the card invisible on the dark
        dashboard. Assert against real pixels, not the stylesheet string."""
        card = CardWidget(Note(title="T", color="Yellow"))
        qtbot.addWidget(card)
        card.resize(200, 160)
        card.show()
        qtbot.waitExposed(card)

        pixel = card.grab().toImage().pixelColor(100, 80)
        assert (pixel.red(), pixel.green(), pixel.blue()) == (0xFF, 0xF9, 0xC4)

    def test_each_color_paints_its_own_background(self, qtbot) -> None:
        from notsucky.utils.constants import COLORS

        for name, scheme in COLORS.items():
            card = CardWidget(Note(title="T", color=name))
            qtbot.addWidget(card)
            card.resize(200, 160)
            card.show()
            qtbot.waitExposed(card)
            assert card.grab().toImage().pixelColor(100, 80).name().upper() == (
                scheme["bg"].upper()
            ), name

    def test_empty_content_shows_a_placeholder(self, qtbot) -> None:
        from PySide6.QtWidgets import QLabel

        card = CardWidget(Note(title="T", content=""))
        qtbot.addWidget(card)
        texts = [lbl.text() for lbl in card.findChildren(QLabel)]
        assert "(empty)" in texts

    def test_long_preview_is_truncated_with_an_ellipsis(self, qtbot) -> None:
        from PySide6.QtWidgets import QLabel

        card = CardWidget(Note(title="T", content="x" * 500))
        qtbot.addWidget(card)
        preview = [lbl.text() for lbl in card.findChildren(QLabel) if lbl.text().startswith("x")]
        assert preview and preview[0].endswith("…")
        assert len(preview[0]) <= 81

    def test_newlines_are_collapsed_in_the_preview(self, qtbot) -> None:
        from PySide6.QtWidgets import QLabel

        card = CardWidget(Note(title="T", content="line one\nline two"))
        qtbot.addWidget(card)
        assert any(lbl.text() == "line one line two" for lbl in card.findChildren(QLabel))

    def test_delete_button_emits_the_note_id(self, qtbot) -> None:
        from PySide6.QtWidgets import QPushButton

        note = Note(title="T")
        card = CardWidget(note)
        qtbot.addWidget(card)
        button = card.findChild(QPushButton)
        with qtbot.waitSignal(card.delete_requested) as blocker:
            button.click()
        assert blocker.args == [note.id]

    def test_double_click_requests_open(self, qtbot) -> None:
        note = Note(title="T")
        card = CardWidget(note)
        qtbot.addWidget(card)
        card.show()
        with qtbot.waitSignal(card.open_requested) as blocker:
            qtbot.mouseDClick(card, Qt.MouseButton.LeftButton)
        assert blocker.args == [note.id]

    def test_drop_from_another_card_requests_a_reorder(self, qtbot) -> None:
        target = CardWidget(Note(id="target00"))
        qtbot.addWidget(target)

        mime = QMimeData()
        mime.setData(NOTE_MIME_TYPE, b"source00")
        event = QDropEvent(
            QPoint(5, 5),
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        with qtbot.waitSignal(target.reorder_requested) as blocker:
            target.dropEvent(event)
        assert blocker.args == ["source00", "target00"]

    def test_dropping_a_card_on_itself_is_ignored(self, qtbot) -> None:
        card = CardWidget(Note(id="same0001"))
        qtbot.addWidget(card)

        mime = QMimeData()
        mime.setData(NOTE_MIME_TYPE, b"same0001")
        event = QDropEvent(
            QPoint(5, 5),
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        with qtbot.assertNotEmitted(card.reorder_requested):
            card.dropEvent(event)

    def test_a_small_movement_does_not_start_a_drag(self, qtbot) -> None:
        """Below the platform drag threshold a press is a click, not a drag."""
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        card = CardWidget(Note(id="card0001"))
        qtbot.addWidget(card)
        card.show()

        card.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(10, 10),
                QPointF(10, 10),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert card._press_pos is not None

        with mock.patch.object(CardWidget, "grab") as grab:
            card.mouseMoveEvent(
                QMouseEvent(
                    QEvent.Type.MouseMove,
                    QPointF(11, 11),
                    QPointF(11, 11),
                    Qt.MouseButton.NoButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
            )
            grab.assert_not_called()

    def test_releasing_clears_the_press_anchor(self, qtbot) -> None:
        card = CardWidget(Note(id="card0001"))
        qtbot.addWidget(card)
        card.show()
        qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        qtbot.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        assert card._press_pos is None

    def test_drag_enter_highlights_and_leave_clears(self, qtbot) -> None:
        card = CardWidget(Note(id="card0001"))
        qtbot.addWidget(card)

        mime = QMimeData()
        mime.setData(NOTE_MIME_TYPE, b"other001")
        enter = QDragEnterEvent(
            QPoint(5, 5),
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        card.dragEnterEvent(enter)
        assert enter.isAccepted()
        assert card._drop_active is True

        from PySide6.QtGui import QDragLeaveEvent

        card.dragLeaveEvent(QDragLeaveEvent())
        assert card._drop_active is False

    def test_foreign_drag_is_rejected(self, qtbot) -> None:
        card = CardWidget(Note(id="card0001"))
        qtbot.addWidget(card)

        mime = QMimeData()
        mime.setText("some text")
        event = QDragEnterEvent(
            QPoint(5, 5),
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        card.dragEnterEvent(event)
        assert not event.isAccepted()


class TestRelativeTime:
    def test_recent_reads_as_just_now(self) -> None:
        from notsucky.models.note import utc_now

        assert format_relative(utc_now()) == "just now"

    def test_old_timestamps_render_as_a_date(self) -> None:
        assert format_relative("2001-02-03T04:05:06+00:00").startswith("2001-02-0")

    @pytest.mark.parametrize("value", ["", "not a date", None, "2026-13-45"])
    def test_bad_timestamps_do_not_raise(self, value) -> None:
        assert format_relative(value) == "unknown"

    def test_naive_timestamps_from_v1_still_parse(self) -> None:
        assert format_relative("2020-05-18T00:39:27.484082") != "unknown"


class TestNoteWidget:
    def test_content_is_loaded_into_the_editor(self, qtbot) -> None:
        note = NoteService.create(title="T", content="hello")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        assert widget.text_edit.toPlainText() == "hello"

    def test_typing_is_debounced_into_a_single_save(self, qtbot) -> None:
        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)

        with mock.patch.object(
            FileManager, "save_note", wraps=FileManager.save_note
        ) as spy:
            for char in "hello world":
                widget.text_edit.insertPlainText(char)
            assert spy.call_count == 0  # nothing written mid-burst
            _flush(widget)
        assert FileManager.load_by_id(note.id).content == "hello world"

    def test_title_edits_persist_on_flush(self, qtbot) -> None:
        note = NoteService.create(title="Before")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)

        widget.title_input.setText("After")
        _flush(widget)
        assert FileManager.load_by_id(note.id).title == "After"

    def test_closing_flushes_unsaved_edits(self, qtbot) -> None:
        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)

        widget.text_edit.setPlainText("typed but not yet debounced")
        widget.close()
        assert FileManager.load_by_id(note.id).content == "typed but not yet debounced"

    def test_hiding_flushes_unsaved_edits(self, qtbot) -> None:
        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.show()

        widget.text_edit.setPlainText("minimized content")
        widget.hide()
        assert FileManager.load_by_id(note.id).content == "minimized content"

    def test_content_is_capped_at_the_storage_limit(self, qtbot) -> None:
        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)

        widget.text_edit.setPlainText("z" * 1_000_050)
        assert len(widget.text_edit.toPlainText()) == 1_000_000

    def test_color_change_persists_and_restyles(self, qtbot) -> None:
        note = NoteService.create(title="T", color="Yellow")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)

        widget.change_color("Blue")
        assert FileManager.load_by_id(note.id).color == "Blue"
        assert any(dot.isChecked() for dot in widget._dots if dot.color_name == "Blue")

    def test_an_off_screen_note_is_pulled_back(self, qtbot) -> None:
        note = NoteService.create(title="Runaway")
        NoteService.update_geometry(note, -45088, 33945, 320, 280)

        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        assert widget.x() > -10_000
        assert widget.y() < 10_000

    def test_a_saved_size_is_restored(self, qtbot) -> None:
        note = NoteService.create(title="T")
        NoteService.update_geometry(note, 40, 40, 480, 400)

        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        assert (widget.width(), widget.height()) == (480, 400)

    def test_dragging_does_not_accumulate_offset(self, qtbot) -> None:
        """The v1 bug: each move applied a delta measured from the press."""
        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.show()
        widget.move(200, 200)

        widget._drag_offset = QPoint(10, 10)
        for _ in range(20):
            # Same cursor position every time: a correct implementation keeps
            # the window still, the accumulating one walks it off-screen.
            widget.move(QPoint(260, 260) - widget._drag_offset)
        assert (widget.x(), widget.y()) == (250, 250)

    def test_save_failure_is_reported_not_swallowed(self, qtbot) -> None:
        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.text_edit.setPlainText("new text")

        with mock.patch.object(
            FileManager, "save_note", side_effect=StorageError("disk full")
        ), qtbot.waitSignal(widget.save_failed) as blocker:
            _flush(widget)
        assert blocker.args[0] == note.id
        assert "⚠" in widget.status_label.text()

    def test_pressing_the_title_bar_starts_a_drag(self, qtbot) -> None:
        """A childAt() guard here would make the window undraggable."""
        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)

        # Posted to the drag handle: inert chrome must bubble the press up.
        qtbot.mousePress(widget.drag_handle, Qt.MouseButton.LeftButton, pos=QPoint(5, 8))
        assert widget._drag_offset is not None

    def test_the_drag_handle_is_a_drag_handle(self, qtbot) -> None:
        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)

        centre = widget.drag_handle.mapTo(widget, widget.drag_handle.rect().center())
        assert widget._is_drag_handle(centre) is True

    def test_the_note_body_paints_its_color(self, qtbot) -> None:
        note = NoteService.create(title="T", color="Green")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.resize(300, 240)
        widget.show()
        qtbot.waitExposed(widget)

        # A point in the editor area, below the title bar.
        assert widget.grab().toImage().pixelColor(150, 120).name().upper() == "#C8E6C9"

    def test_the_status_bar_chrome_is_a_drag_handle(self, qtbot) -> None:
        """The char-count area is inert chrome, so it drags. The tags field
        beside it is a real control, so it must not."""
        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)

        label = widget.status_label
        assert widget._is_drag_handle(label.mapTo(widget, label.rect().center())) is True

        tags = widget.tags_input
        assert widget._is_drag_handle(tags.mapTo(widget, tags.rect().center())) is False

    def test_interactive_controls_are_not_drag_handles(self, qtbot) -> None:
        """Pressing the editor, the title field, or a button must not drag."""
        note = NoteService.create(title="T", content="text")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)

        for control in (widget.text_edit, widget.title_input, widget._dots[0]):
            centre = control.mapTo(widget, control.rect().center())
            assert widget._is_drag_handle(centre) is False, control

    def test_pressing_the_editor_does_not_start_a_drag(self, qtbot) -> None:
        note = NoteService.create(title="T", content="text")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.show()
        qtbot.waitExposed(widget)

        viewport = widget.text_edit.viewport()
        qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        assert widget._drag_offset is None

    def test_a_full_drag_moves_the_window_and_persists(self, qtbot) -> None:
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.show()
        widget.move(300, 300)

        # Local point on the drag handle, 10px in from the window origin.
        handle = widget.drag_handle.mapTo(widget, widget.drag_handle.rect().center())

        def event(kind, global_x, global_y, buttons):
            return QMouseEvent(
                kind,
                QPointF(handle),
                QPointF(global_x, global_y),
                Qt.MouseButton.LeftButton,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            )

        widget.mousePressEvent(
            event(QEvent.Type.MouseButtonPress, 310, 310, Qt.MouseButton.LeftButton)
        )
        widget.mouseMoveEvent(
            event(QEvent.Type.MouseMove, 410, 360, Qt.MouseButton.LeftButton)
        )
        widget.mouseReleaseEvent(
            event(QEvent.Type.MouseButtonRelease, 410, 360, Qt.MouseButton.NoButton)
        )

        assert (widget.x(), widget.y()) == (400, 350)
        assert widget._drag_offset is None
        stored = FileManager.load_by_id(note.id)
        assert (stored.x, stored.y) == (400, 350)

    def test_a_drag_release_clamps_back_on_screen(self, qtbot) -> None:
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.show()

        widget._drag_offset = QPoint(0, 0)
        widget.move(-9000, -9000)
        widget.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(0, 0),
                QPointF(0, 0),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert widget.x() > -9000

    def test_minimize_button_emits_and_flushes(self, qtbot) -> None:
        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)
        widget.text_edit.setPlainText("pending")

        with qtbot.waitSignal(widget.minimize_requested):
            widget._request_minimize()
        assert FileManager.load_by_id(note.id).content == "pending"


class TestDashboardGrid:
    def test_empty_state_is_shown_with_no_notes(self, dashboard) -> None:
        from PySide6.QtWidgets import QLabel

        labels = [lbl.text() for lbl in dashboard.grid_frame.findChildren(QLabel)]
        assert any("No notes yet" in text for text in labels)

    def test_notes_become_cards(self, dashboard) -> None:
        for title in ("one", "two", "three"):
            NoteService.create(title=title)
        dashboard.reload()
        assert len(dashboard.grid_frame.findChildren(CardWidget)) == 3

    def test_filter_narrows_the_grid(self, dashboard) -> None:
        NoteService.create(title="Groceries")
        NoteService.create(title="Meeting notes")
        dashboard.reload()

        dashboard.search_input.setText("groc")
        dashboard._rebuild_grid()
        cards = dashboard.grid_frame.findChildren(CardWidget)
        assert [c.note.title for c in cards] == ["Groceries"]

    def test_filter_matches_content_too(self, dashboard) -> None:
        NoteService.create(title="A", content="buy milk")
        NoteService.create(title="B", content="call dentist")
        dashboard.reload()

        dashboard.search_input.setText("milk")
        dashboard._rebuild_grid()
        assert len(dashboard.grid_frame.findChildren(CardWidget)) == 1

    def test_no_match_shows_the_filter_empty_state(self, dashboard) -> None:
        from PySide6.QtWidgets import QLabel

        NoteService.create(title="A")
        dashboard.reload()
        dashboard.search_input.setText("zzzzz")
        dashboard._rebuild_grid()

        labels = [lbl.text() for lbl in dashboard.grid_frame.findChildren(QLabel)]
        assert any("No notes match" in text for text in labels)

    def test_escape_clears_the_filter(self, dashboard) -> None:
        dashboard.search_input.setText("something")
        dashboard._clear_search()
        assert dashboard.search_input.text() == ""

    def test_search_does_not_re_read_the_disk(self, dashboard) -> None:
        NoteService.create(title="Cached")
        dashboard.reload()

        with mock.patch.object(FileManager, "load_all", return_value=[]) as spy:
            dashboard.search_input.setText("cac")
            dashboard._rebuild_grid()
            assert spy.call_count == 0
        assert len(dashboard.grid_frame.findChildren(CardWidget)) == 1

    def test_column_count_is_within_bounds(self, dashboard) -> None:
        from notsucky.utils.constants import MAX_GRID_COLUMNS, MIN_GRID_COLUMNS

        assert MIN_GRID_COLUMNS <= dashboard._column_count() <= MAX_GRID_COLUMNS


class TestDashboardRendering:
    """Pixel checks against a card *inside the dashboard*.

    A standalone card painting correctly proves nothing about the real
    window: Qt gives an ancestor's stylesheet precedence over the
    application's, so the dashboard's own sheet can suppress the card rules
    and leave every card transparent. That regression shipped once because
    the only pixel test used a parentless card.
    """

    def _card_pixel(self, window, card):
        image = window.grab().toImage()
        return image.pixelColor(card.mapTo(window, card.rect().center())).name().upper()

    def test_a_card_in_the_grid_paints_its_colour(self, qtbot) -> None:
        NoteService.create(title="Yellow one", color="Yellow")
        window = DashboardWindow()
        qtbot.addWidget(window)
        window.resize(900, 600)
        window.show()
        qtbot.waitExposed(window)

        card = window.grid_frame.findChildren(CardWidget)[0]
        assert self._card_pixel(window, card) == "#FFF9C4"

    def test_every_colour_survives_the_dashboard_cascade(self, qtbot) -> None:
        from notsucky.utils.constants import COLORS

        for name in COLORS:
            NoteService.create(title=f"{name} note", color=name)

        window = DashboardWindow()
        qtbot.addWidget(window)
        window.resize(1100, 800)
        window.show()
        qtbot.waitExposed(window)
        window.finish_building_grid()

        for card in window.grid_frame.findChildren(CardWidget):
            expected = COLORS[card.note.color]["bg"].upper()
            assert self._card_pixel(window, card) == expected, card.note.color

    def test_the_card_never_shows_the_dark_chrome_behind_it(self, qtbot) -> None:
        from notsucky.utils.constants import CHROME_BG

        NoteService.create(title="Any")
        window = DashboardWindow()
        qtbot.addWidget(window)
        window.resize(900, 600)
        window.show()
        qtbot.waitExposed(window)

        card = window.grid_frame.findChildren(CardWidget)[0]
        assert self._card_pixel(window, card) != CHROME_BG.upper()


class TestDashboardLifecycle:
    def test_create_note_opens_a_window(self, dashboard) -> None:
        dashboard.create_note()
        assert len(dashboard._open_notes) == 1
        assert len(FileManager.load_all()) == 1

    def test_opening_the_same_note_twice_reuses_the_window(self, dashboard) -> None:
        note = NoteService.create(title="T")
        dashboard.reload()
        dashboard.open_note(note.id)
        first = dashboard._open_notes[note.id]
        dashboard.open_note(note.id)
        assert dashboard._open_notes[note.id] is first
        assert len(dashboard._open_notes) == 1

    def test_opening_a_deleted_note_recovers_gracefully(self, dashboard) -> None:
        note = NoteService.create(title="Ghost")
        dashboard.reload()
        FileManager.delete_note(note)

        dashboard.open_note(note.id)
        assert note.id not in dashboard._open_notes

    def test_closing_a_note_drops_the_reference(self, dashboard) -> None:
        note = NoteService.create(title="T")
        dashboard.reload()
        dashboard.open_note(note.id)
        dashboard.close_note(note.id)
        assert dashboard._open_notes == {}

    def test_minimize_moves_the_note_to_the_dock(self, dashboard) -> None:
        note = NoteService.create(title="T")
        dashboard.reload()
        dashboard.open_note(note.id)
        dashboard.minimize_note(note.id)

        assert dashboard._minimized_ids == [note.id]
        assert dashboard.dock_frame.isVisible() or dashboard.isHidden()
        assert FileManager.load_by_id(note.id).minimized is True

    def test_restore_clears_the_minimized_flag(self, dashboard) -> None:
        """v1 left minimized=True on disk forever after a restore."""
        note = NoteService.create(title="T")
        dashboard.reload()
        dashboard.open_note(note.id)
        dashboard.minimize_note(note.id)
        dashboard.restore_note(note.id)

        assert dashboard._minimized_ids == []
        assert FileManager.load_by_id(note.id).minimized is False

    def test_the_dock_is_rebuilt_at_startup(self, qtbot) -> None:
        """v1 never repopulated the dock, stranding minimized notes."""
        note = NoteService.create(title="Docked")
        NoteService.set_minimized(note, True)

        window = DashboardWindow()
        qtbot.addWidget(window)
        assert window._minimized_ids == [note.id]

    def test_the_dock_hides_when_empty(self, dashboard) -> None:
        assert dashboard.dock_frame.isVisible() is False

    def test_a_dock_entry_for_a_deleted_note_is_dropped(self, dashboard) -> None:
        note = NoteService.create(title="T")
        NoteService.set_minimized(note, True)
        dashboard.reload(restore_dock=True)
        assert dashboard._minimized_ids == [note.id]

        FileManager.delete_note(note)
        dashboard.reload()
        assert dashboard._minimized_ids == []

    def test_restoring_a_hidden_window_does_not_create_a_second_one(self, dashboard) -> None:
        note = NoteService.create(title="T")
        dashboard.reload()
        dashboard.open_note(note.id)
        original = dashboard._open_notes[note.id]

        dashboard.minimize_note(note.id)
        dashboard.restore_note(note.id)
        assert dashboard._open_notes[note.id] is original
        assert len(dashboard._open_notes) == 1


class TestDashboardDeletion:
    def test_delete_removes_the_note_after_confirmation(self, dashboard, monkeypatch) -> None:
        note = NoteService.create(title="Doomed")
        dashboard.reload()
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )

        dashboard.delete_note(note.id)
        assert FileManager.load_all() == []

    def test_declining_the_prompt_keeps_the_note(self, dashboard, monkeypatch) -> None:
        note = NoteService.create(title="Safe")
        dashboard.reload()
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
        )

        dashboard.delete_note(note.id)
        assert len(FileManager.load_all()) == 1

    def test_deleting_an_open_note_does_not_resurrect_it(self, dashboard, monkeypatch) -> None:
        """v1 left the widget in _open_notes, so auto-save rewrote the file."""
        note = NoteService.create(title="Doomed")
        dashboard.reload()
        dashboard.open_note(note.id)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )

        dashboard.delete_note(note.id)
        dashboard._auto_save_loop()
        assert FileManager.load_all() == []
        assert dashboard._open_notes == {}

    def test_deleting_a_minimized_note_clears_the_dock(self, dashboard, monkeypatch) -> None:
        note = NoteService.create(title="T")
        dashboard.reload()
        dashboard.open_note(note.id)
        dashboard.minimize_note(note.id)
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )

        dashboard.delete_note(note.id)
        assert dashboard._minimized_ids == []


class TestTagFilterBar:
    def _chips(self, dashboard):
        from PySide6.QtWidgets import QPushButton

        return [
            b
            for b in dashboard.tag_content.findChildren(QPushButton)
            if b.objectName() == "tagChip"
        ]

    def test_the_bar_is_hidden_with_no_tags(self, dashboard) -> None:
        NoteService.create(title="untagged")
        dashboard.reload()
        assert dashboard.tag_bar.isVisible() is False

    def test_a_chip_appears_for_each_tag(self, dashboard) -> None:
        note = NoteService.create(title="T")
        NoteService.set_tags(note, ["work", "home"])
        dashboard.reload()

        labels = [c.text() for c in self._chips(dashboard)]
        assert sorted(labels) == ["home (1)", "work (1)"]

    def test_chips_show_how_many_notes_carry_the_tag(self, dashboard) -> None:
        for _ in range(3):
            NoteService.set_tags(NoteService.create(title="n"), ["work"])
        dashboard.reload()
        assert self._chips(dashboard)[0].text() == "work (3)"

    def test_clicking_a_chip_filters_the_grid(self, dashboard) -> None:
        tagged = NoteService.create(title="Tagged")
        NoteService.set_tags(tagged, ["work"])
        NoteService.create(title="Untagged")
        dashboard.reload()
        assert len(dashboard.grid_frame.findChildren(CardWidget)) == 2

        dashboard.toggle_tag("work")
        cards = dashboard.grid_frame.findChildren(CardWidget)
        assert [c.note.title for c in cards] == ["Tagged"]

    def test_two_tags_narrow_further(self, dashboard) -> None:
        both = NoteService.create(title="Both")
        NoteService.set_tags(both, ["work", "urgent"])
        one = NoteService.create(title="One")
        NoteService.set_tags(one, ["work"])
        dashboard.reload()

        dashboard.toggle_tag("work")
        dashboard.toggle_tag("urgent")
        cards = dashboard.grid_frame.findChildren(CardWidget)
        assert [c.note.title for c in cards] == ["Both"]

    def test_clicking_again_removes_the_filter(self, dashboard) -> None:
        NoteService.set_tags(NoteService.create(title="T"), ["work"])
        NoteService.create(title="Other")
        dashboard.reload()

        dashboard.toggle_tag("work")
        dashboard.toggle_tag("work")
        assert len(dashboard.grid_frame.findChildren(CardWidget)) == 2

    def test_escape_clears_tags_as_well_as_text(self, dashboard) -> None:
        NoteService.set_tags(NoteService.create(title="T"), ["work"])
        dashboard.reload()
        dashboard.toggle_tag("work")
        dashboard.search_input.setText("zzz")

        dashboard._clear_filters()
        assert dashboard._selected_tags == set()
        assert dashboard.search_input.text() == ""

    def test_a_selection_is_dropped_when_its_tag_disappears(self, dashboard) -> None:
        note = NoteService.create(title="T")
        NoteService.set_tags(note, ["work"])
        dashboard.reload()
        dashboard.toggle_tag("work")

        NoteService.set_tags(note, [])
        dashboard.reload()
        assert dashboard._selected_tags == set()

    def test_a_card_shows_its_tags(self, dashboard) -> None:
        from PySide6.QtWidgets import QLabel

        NoteService.set_tags(NoteService.create(title="T"), ["alpha", "beta"])
        dashboard.reload()

        card = dashboard.grid_frame.findChildren(CardWidget)[0]
        text = " ".join(lbl.text() for lbl in card.findChildren(QLabel))
        assert "alpha" in text and "beta" in text

    def test_a_card_summarises_many_tags(self, qtbot) -> None:
        from PySide6.QtWidgets import QLabel

        from notsucky.utils.constants import CARD_TAG_LIMIT

        note = Note(title="T", tags=[f"tag{i}" for i in range(CARD_TAG_LIMIT + 3)])
        card = CardWidget(note)
        qtbot.addWidget(card)

        text = " ".join(lbl.text() for lbl in card.findChildren(QLabel))
        assert "+3" in text


class TestNoteTagEditor:
    def test_existing_tags_are_shown(self, qtbot) -> None:
        note = NoteService.create(title="T")
        NoteService.set_tags(note, ["work", "home"])

        widget = NoteWidget(FileManager.load_by_id(note.id))
        qtbot.addWidget(widget)
        assert widget.tags_input.text() == "work, home"

    def test_typing_tags_persists_them(self, qtbot) -> None:
        note = NoteService.create(title="T")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)

        widget.tags_input.setText("Work, Urgent")
        _flush(widget)
        assert FileManager.load_by_id(note.id).tags == ["work", "urgent"]

    def test_clearing_the_field_removes_the_tags(self, qtbot) -> None:
        note = NoteService.create(title="T")
        NoteService.set_tags(note, ["work"])
        widget = NoteWidget(FileManager.load_by_id(note.id))
        qtbot.addWidget(widget)

        widget.tags_input.setText("")
        _flush(widget)
        assert FileManager.load_by_id(note.id).tags == []

    def test_tags_do_not_disturb_the_content(self, qtbot) -> None:
        note = NoteService.create(title="T", content="precious")
        widget = NoteWidget(note)
        qtbot.addWidget(widget)

        widget.tags_input.setText("x")
        _flush(widget)
        assert FileManager.load_by_id(note.id).content == "precious"


class TestThemeToggle:
    def test_the_dashboard_starts_in_the_stored_theme(self, qtbot) -> None:
        from notsucky.utils import theme

        theme.set_theme("light")
        window = DashboardWindow()
        qtbot.addWidget(window)
        assert theme.THEMES["light"]["bg"] in window.styleSheet()

    def test_toggling_restyles_the_shell(self, dashboard) -> None:
        from notsucky.utils import theme

        before = dashboard.styleSheet()
        name = dashboard.toggle_theme()
        assert name == "light"
        assert dashboard.styleSheet() != before
        assert theme.THEMES["light"]["bg"] in dashboard.styleSheet()

    def test_toggling_twice_returns_to_dark(self, dashboard) -> None:
        dashboard.toggle_theme()
        assert dashboard.toggle_theme() == "dark"

    def test_the_choice_survives_a_restart(self, dashboard, qtbot) -> None:
        from notsucky.utils import theme

        dashboard.toggle_theme()
        fresh = DashboardWindow()
        qtbot.addWidget(fresh)
        assert theme.THEMES["light"]["bg"] in fresh.styleSheet()

    def test_the_button_label_flips(self, dashboard) -> None:
        dashboard.toggle_theme()
        assert "Dark" in dashboard.theme_btn.text()
        dashboard.toggle_theme()
        assert "Light" in dashboard.theme_btn.text()

    def test_note_colours_do_not_change_with_the_theme(self, dashboard, qtbot) -> None:
        """A note's colour identifies the note; a display setting must not
        change what it means."""
        from notsucky.utils.constants import COLORS

        NoteService.create(title="T", color="Blue")
        dashboard.reload()
        card = dashboard.grid_frame.findChildren(CardWidget)[0]
        dashboard.show()
        qtbot.waitExposed(dashboard)

        def card_pixel():
            image = dashboard.grab().toImage()
            return image.pixelColor(card.mapTo(dashboard, card.rect().center())).name()

        dark_pixel = card_pixel()
        dashboard.toggle_theme()
        assert card_pixel() == dark_pixel == COLORS["Blue"]["bg"].lower()


class TestSearchHighlighting:
    def test_a_matching_card_marks_the_match(self, dashboard) -> None:
        from PySide6.QtWidgets import QLabel

        NoteService.create(title="Groceries", content="buy milk and bread")
        dashboard.reload()
        dashboard.search_input.setText("milk")
        dashboard._rebuild_grid()

        card = dashboard.grid_frame.findChildren(CardWidget)[0]
        markup = " ".join(lbl.text() for lbl in card.findChildren(QLabel))
        assert "<span" in markup and "milk</span>" in markup

    def test_no_query_means_no_markup(self, dashboard) -> None:
        from PySide6.QtWidgets import QLabel

        NoteService.create(title="Plain", content="nothing special")
        dashboard.reload()

        card = dashboard.grid_frame.findChildren(CardWidget)[0]
        markup = " ".join(lbl.text() for lbl in card.findChildren(QLabel))
        assert "<span" not in markup

    def test_a_note_containing_html_is_not_rendered_as_html(self, qtbot) -> None:
        """The card must show <b> as characters, not turn the text bold."""
        from PySide6.QtWidgets import QLabel

        card = CardWidget(Note(title="T", content="<b>not bold</b>"), query="bold")
        qtbot.addWidget(card)
        markup = " ".join(lbl.text() for lbl in card.findChildren(QLabel))
        assert "&lt;b&gt;" in markup
        assert "<b>" not in markup

    def test_the_preview_slides_to_show_a_late_match(self, dashboard) -> None:
        from PySide6.QtWidgets import QLabel

        NoteService.create(title="Long", content=("filler " * 200) + "needle here")
        dashboard.reload()
        dashboard.search_input.setText("needle")
        dashboard._rebuild_grid()

        card = dashboard.grid_frame.findChildren(CardWidget)[0]
        markup = " ".join(lbl.text() for lbl in card.findChildren(QLabel))
        assert "needle" in markup


class TestDashboardExport:
    def test_export_writes_every_note(self, dashboard, tmp_path, monkeypatch) -> None:
        from PySide6.QtWidgets import QFileDialog

        for title in ("one", "two"):
            NoteService.create(title=title, content="body")
        dashboard.reload()

        target = tmp_path / "exported"
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(target)
        )
        dashboard.export_notes()

        assert len(list(target.glob("*.md"))) == 2
        assert "Exported 2 notes" in dashboard.statusBar().currentMessage()

    def test_cancelling_the_dialog_writes_nothing(
        self, dashboard, tmp_path, monkeypatch
    ) -> None:
        from PySide6.QtWidgets import QFileDialog

        NoteService.create(title="one")
        dashboard.reload()
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: "")

        dashboard.export_notes()
        assert list(tmp_path.rglob("*.md")) == []

    def test_exporting_an_empty_store_says_so(self, dashboard) -> None:
        dashboard.export_notes()
        assert "Nothing to export" in dashboard.statusBar().currentMessage()

    def test_a_failing_export_is_reported_not_raised(
        self, dashboard, tmp_path, monkeypatch
    ) -> None:
        from PySide6.QtWidgets import QFileDialog

        from notsucky.services import export as export_service

        NoteService.create(title="one")
        dashboard.reload()
        monkeypatch.setattr(
            QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path)
        )
        monkeypatch.setattr(
            export_service, "export_all", lambda *a, **k: (_ for _ in ()).throw(OSError("full"))
        )

        dashboard.export_notes()
        assert "Export failed" in dashboard.statusBar().currentMessage()


class TestDashboardUndo:
    @pytest.fixture()
    def confirm_delete(self, monkeypatch):
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
        )

    def test_undo_restores_the_deleted_note(self, dashboard, confirm_delete) -> None:
        note = NoteService.create(title="Oops", content="wanted this")
        dashboard.reload()
        dashboard.delete_note(note.id)
        assert FileManager.load_all() == []

        dashboard.undo_delete()
        restored = FileManager.load_all()
        assert [n.title for n in restored] == ["Oops"]
        assert restored[0].content == "wanted this"

    def test_the_restored_note_reappears_in_the_grid(self, dashboard, confirm_delete) -> None:
        note = NoteService.create(title="Oops")
        dashboard.reload()
        dashboard.delete_note(note.id)
        dashboard.undo_delete()
        assert len(dashboard.grid_frame.findChildren(CardWidget)) == 1

    def test_undo_pops_one_deletion_at_a_time(self, dashboard, confirm_delete) -> None:
        first = NoteService.create(title="first")
        second = NoteService.create(title="second")
        dashboard.reload()
        dashboard.delete_note(first.id)
        dashboard.delete_note(second.id)

        dashboard.undo_delete()
        assert [n.title for n in FileManager.load_all()] == ["second"]
        dashboard.undo_delete()
        assert sorted(n.title for n in FileManager.load_all()) == ["first", "second"]

    def test_undo_with_nothing_deleted_says_so(self, dashboard) -> None:
        dashboard.undo_delete()
        assert "Nothing to undo" in dashboard.statusBar().currentMessage()

    def test_the_delete_message_advertises_undo(self, dashboard, confirm_delete) -> None:
        note = NoteService.create(title="Oops")
        dashboard.reload()
        dashboard.delete_note(note.id)
        assert "Ctrl+Z" in dashboard.statusBar().currentMessage()

    def test_undo_after_the_trash_was_emptied_is_graceful(
        self, dashboard, confirm_delete
    ) -> None:
        note = NoteService.create(title="Oops")
        dashboard.reload()
        dashboard.delete_note(note.id)
        FileManager.empty_trash()

        dashboard.undo_delete()  # must not raise
        assert FileManager.load_all() == []


class TestApplicationIcon:
    def test_the_icon_is_not_null(self, qtbot) -> None:
        from notsucky.views.icon import ICON_SIZES, app_icon

        icon = app_icon()
        assert not icon.isNull()
        assert len(icon.availableSizes()) == len(ICON_SIZES)

    def test_every_size_renders_opaque_pixels(self, qtbot) -> None:
        from PySide6.QtCore import QSize

        from notsucky.views.icon import ICON_SIZES, app_icon

        icon = app_icon()
        for size in ICON_SIZES:
            image = icon.pixmap(QSize(size, size)).toImage()
            assert image.width() == size
            centre = image.pixelColor(size // 2, size // 2)
            assert centre.alpha() == 255, f"{size}px icon is transparent at its centre"

    def test_the_corners_stay_transparent(self, qtbot) -> None:
        from notsucky.views.icon import app_icon

        image = app_icon().pixmap(64, 64).toImage()
        assert image.pixelColor(0, 0).alpha() == 0


class TestDashboardReorder:
    def test_dropping_one_card_on_another_persists_the_order(self, dashboard) -> None:
        a = NoteService.create(title="a")
        b = NoteService.create(title="b")
        c = NoteService.create(title="c")
        for position, note in enumerate((a, b, c), start=1):
            note.order = position
            FileManager.save_note(note)
        dashboard.reload()

        dashboard._on_reorder(c.id, a.id)
        assert [n.title for n in FileManager.load_all()] == ["c", "a", "b"]

    def test_reordering_is_blocked_while_filtering(self, dashboard) -> None:
        a = NoteService.create(title="alpha")
        NoteService.create(title="beta")
        dashboard.reload()
        dashboard.search_input.setText("alpha")
        dashboard._rebuild_grid()

        before = [n.order for n in FileManager.load_all()]
        dashboard._on_reorder(a.id, a.id)
        assert [n.order for n in FileManager.load_all()] == before


class TestDashboardResilience:
    def test_auto_save_survives_a_failing_note(self, dashboard) -> None:
        note = NoteService.create(title="T")
        dashboard.reload()
        dashboard.open_note(note.id)

        with mock.patch.object(
            NoteWidget, "flush", side_effect=RuntimeError("boom")
        ):
            dashboard._auto_save_loop()  # must not propagate

    def test_a_storage_failure_surfaces_in_the_status_bar(self, dashboard) -> None:
        dashboard._on_save_failed("abc12345", "disk full")
        assert "disk full" in dashboard.statusBar().currentMessage()

    def test_closing_the_dashboard_flushes_open_notes(self, qtbot) -> None:
        note = NoteService.create(title="T")
        window = DashboardWindow()
        qtbot.addWidget(window)
        window.open_note(note.id)
        window._open_notes[note.id].text_edit.setPlainText("last words")

        window.close()
        assert FileManager.load_by_id(note.id).content == "last words"
        assert window._open_notes == {}

    def test_a_corrupt_file_does_not_break_the_grid(self, dashboard, notes_dir) -> None:
        NoteService.create(title="Good")
        (notes_dir / "broken.json").write_text("{{{", encoding="utf-8")

        dashboard.reload()
        assert len(dashboard.grid_frame.findChildren(CardWidget)) == 1
