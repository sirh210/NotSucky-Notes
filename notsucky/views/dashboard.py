"""Dashboard window - main application view."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from notsucky.models.note import Note
from notsucky.services import backup
from notsucky.services.file_manager import (
    FileManager,
    StorageError,
    all_tags,
    filter_notes,
    sort_for_display,
    tag_counts,
)
from notsucky.services.note_service import NoteService
from notsucky.utils.constants import (
    AUTO_SAVE_INTERVAL_MS,
    GRID_CHUNK_SIZE,
    GRID_FIRST_CHUNK,
    GRID_MARGIN,
    GRID_SPACING,
    MAX_GRID_COLUMNS,
    MIN_CARD_WIDTH,
    MIN_GRID_COLUMNS,
    SEARCH_DEBOUNCE_MS,
    color_scheme,
)
from notsucky.utils.geometry import columns_for_width
from notsucky.utils.theme import current_theme, palette, toggle_theme
from notsucky.views.card_widget import CardWidget
from notsucky.views.note_widget import NoteWidget
from notsucky.views.qt_support import close_and_delete, live

logger = logging.getLogger(__name__)


def clear_layout(layout: QLayout) -> None:
    """Remove and delete every widget in ``layout``.

    ``takeAt`` is documented to return None past the end; guarding it means
    a concurrent modification cannot turn a rebuild into a crash.
    """
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            break
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


class DashboardWindow(QMainWindow):
    """Main dashboard with a searchable, reorderable grid of note cards."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NotSucky Notes")
        self.resize(950, 680)
        self.setMinimumSize(520, 400)

        # ─── State ────────────────────────────────────────────────
        self._open_notes: dict[str, NoteWidget] = {}
        self._minimized_ids: list[str] = []
        self._notes: list[Note] = []
        self._visible_notes: list[Note] = []
        self._columns = 0
        self._built_cards = 0
        self._shutting_down = False
        self._selected_tags: set[str] = set()
        # Trash paths of deleted notes, most recent last. Survives for the
        # session; the files themselves survive TRASH_RETENTION_DAYS.
        self._undo_stack: list[Path | None] = []

        self._build_ui()
        self._install_shortcuts()

        # ─── Timers ───────────────────────────────────────────────
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._rebuild_grid)

        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(80)
        self._relayout_timer.timeout.connect(self._rebuild_grid)

        # Streams the remaining cards in after the first chunk has painted.
        self._card_timer = QTimer(self)
        self._card_timer.setSingleShot(True)
        self._card_timer.setInterval(0)
        self._card_timer.timeout.connect(self._add_next_chunk)

        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.timeout.connect(self._auto_save_loop)
        self._auto_save_timer.start(AUTO_SAVE_INTERVAL_MS)

        self.reload(restore_dock=True)

    # ─── Construction ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._apply_theme()

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self._build_header())
        main_layout.addWidget(self._build_tag_bar())

        self.grid_scroll = QScrollArea()
        self.grid_scroll.setObjectName("gridScroll")
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.grid_frame = QWidget()
        self.grid_frame.setObjectName("gridFrame")
        self.grid_layout = QGridLayout(self.grid_frame)
        self.grid_layout.setContentsMargins(GRID_MARGIN, 15, GRID_MARGIN, GRID_MARGIN)
        self.grid_layout.setHorizontalSpacing(GRID_SPACING)
        self.grid_layout.setVerticalSpacing(GRID_SPACING)
        self.grid_scroll.setWidget(self.grid_frame)
        main_layout.addWidget(self.grid_scroll, 1)

        main_layout.addWidget(self._build_dock())

        self.setStatusBar(QStatusBar())
        self.statusBar().setSizeGripEnabled(True)

    # ─── Theme ────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        """Restyle the shell from the active palette.

        Only chrome is themed. The six note colours are identical in both
        themes on purpose: a note's colour identifies that note, and having
        it change with a display setting would make it meaningless.

        Every rule is scoped by a selector. A selector-less sheet such as
        `setStyleSheet("background: transparent")` applies to the widget *and
        every descendant*, which is how the grid container once silently
        blanked the background of every card inside it.
        """
        c = palette()
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {c['bg']}; }}
            QWidget#central {{ background-color: {c['bg']}; }}
            QWidget#header, QWidget#dock, QWidget#tagBar {{
                background-color: {c['panel']};
            }}
            QWidget#dock {{ border-top: 1px solid {c['border']}; }}
            QWidget#tagBar {{ border-bottom: 1px solid {c['border']}; }}
            QWidget#gridFrame, QWidget#dockContent, QWidget#headerLeft,
            QWidget#tagContent {{
                background: transparent;
            }}
            QScrollArea#gridScroll, QScrollArea#dockScroll,
            QScrollArea#tagScroll {{
                background: transparent; border: none;
            }}
            QStatusBar {{ background-color: {c['panel']}; color: {c['text_muted']}; }}
            QLabel#appTitle {{
                font-size: 19px; font-weight: bold; color: {c['text']};
                background: transparent;
            }}
            QLabel#pathLabel, QLabel#tagBarLabel, QLabel#dockHint {{
                font-size: 9px; color: {c['text_muted']}; background: transparent;
            }}
            QLabel#emptyState {{
                color: {c['text_muted']}; font-size: 14px; background: transparent;
            }}
            QLineEdit#searchInput {{
                background-color: {c['input_bg']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 6px;
                padding: 7px 8px; font-size: 12px;
            }}
            QLineEdit#searchInput:focus {{ border: 1px solid #4CAF50; }}
            QPushButton#chromeButton {{
                background-color: {c['border']}; color: {c['text']};
                border: none; border-radius: 6px;
            }}
            QPushButton#chromeButton:hover {{ background-color: {c['hover']}; }}
            QPushButton#newButton {{
                background-color: #4CAF50; color: white; border: none;
                border-radius: 6px; font-weight: bold;
            }}
            QPushButton#newButton:hover {{ background-color: #45A049; }}
            QPushButton#tagChip {{
                background-color: {c['chip_bg']}; color: {c['chip_text']};
                border: none; border-radius: 9px;
                padding: 3px 10px; font-size: 10px;
            }}
            QPushButton#tagChip:hover {{ background-color: {c['hover']}; }}
            QPushButton#tagChip:checked {{
                background-color: {c['chip_active_bg']};
                color: {c['chip_active_text']}; font-weight: bold;
            }}
        """)

    def toggle_theme(self) -> str:
        """Switch between the light and dark shell, and remember the choice."""
        name = toggle_theme()
        self._apply_theme()
        if hasattr(self, "theme_btn"):
            self.theme_btn.setText("☾ Dark" if name == "light" else "☀ Light")
            self.theme_btn.setToolTip(
                f"Switch to the {'dark' if name == 'light' else 'light'} theme (Ctrl+T)"
            )
        self.statusBar().showMessage(f"{name.capitalize()} theme", 3000)
        return name

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(68)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(12)

        title_lbl = QLabel("📝 NotSucky Notes")
        title_lbl.setObjectName("appTitle")

        self.path_lbl = QLabel()
        self.path_lbl.setObjectName("pathLabel")
        self.path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        left = QWidget()
        left.setObjectName("headerLeft")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(title_lbl)
        left_layout.addWidget(self.path_lbl)
        layout.addWidget(left, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch(1)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter notes…  (Ctrl+F)")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setAccessibleName("Filter notes")
        self.search_input.setFixedWidth(240)
        self.search_input.setObjectName("searchInput")
        self.search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_input, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch(1)

        stats_btn = QPushButton("📊 Stats")
        stats_btn.setObjectName("chromeButton")
        stats_btn.setFixedSize(88, 34)
        stats_btn.setToolTip("Show statistics about your notes (Ctrl+I)")
        stats_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stats_btn.clicked.connect(self.show_statistics)
        layout.addWidget(stats_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.theme_btn = QPushButton(
            "☾ Dark" if current_theme() == "light" else "☀ Light"
        )
        self.theme_btn.setObjectName("chromeButton")
        self.theme_btn.setFixedSize(84, 34)
        self.theme_btn.setToolTip(
            f"Switch to the {'dark' if current_theme() == 'light' else 'light'} theme (Ctrl+T)"
        )
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self.toggle_theme)
        layout.addWidget(self.theme_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setObjectName("chromeButton")
        refresh_btn.setFixedSize(96, 34)
        refresh_btn.setToolTip("Reload notes from disk (F5)")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(lambda: self.reload())
        layout.addWidget(refresh_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        new_btn = QPushButton("+ New Note")
        new_btn.setObjectName("newButton")
        new_btn.setFixedSize(120, 34)
        new_btn.setToolTip("Create a new note (Ctrl+N)")
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.clicked.connect(self.create_note)
        layout.addWidget(new_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        return header

    # ─── Tag filter bar ───────────────────────────────────────────

    def _build_tag_bar(self) -> QWidget:
        """A row of toggleable tag chips, hidden until a tag exists."""
        self.tag_bar = QWidget()
        self.tag_bar.setObjectName("tagBar")
        self.tag_bar.setFixedHeight(36)

        bar_layout = QHBoxLayout(self.tag_bar)
        bar_layout.setContentsMargins(20, 4, 20, 4)
        bar_layout.setSpacing(8)

        label = QLabel("Tags:")
        label.setObjectName("tagBarLabel")
        bar_layout.addWidget(label)

        self.tag_scroll = QScrollArea()
        self.tag_scroll.setObjectName("tagScroll")
        self.tag_scroll.setWidgetResizable(True)
        self.tag_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.tag_content = QWidget()
        self.tag_content.setObjectName("tagContent")
        self.tag_layout = QHBoxLayout(self.tag_content)
        self.tag_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_layout.setSpacing(6)
        self.tag_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.tag_scroll.setWidget(self.tag_content)

        bar_layout.addWidget(self.tag_scroll, 1)
        self.tag_bar.setVisible(False)
        return self.tag_bar

    def _rebuild_tag_bar(self) -> None:
        """Rebuild the chips from the tags currently in the store."""
        clear_layout(self.tag_layout)

        tags = all_tags(self._notes)
        counts = tag_counts(self._notes)
        # Drop selections whose tag no longer exists on any note.
        self._selected_tags = {t for t in self._selected_tags if t in counts}

        for tag in tags:
            chip = QPushButton(f"{tag} ({counts[tag]})")
            chip.setObjectName("tagChip")
            chip.setCheckable(True)
            chip.setChecked(tag in self._selected_tags)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(f"Show only notes tagged “{tag}”")
            chip.setAccessibleName(f"Filter by tag {tag}")
            chip.clicked.connect(lambda _checked=False, t=tag: self.toggle_tag(t))
            self.tag_layout.addWidget(chip)

        self.tag_bar.setVisible(bool(tags))

    def toggle_tag(self, tag: str) -> None:
        """Add or remove a tag from the active filter."""
        if tag in self._selected_tags:
            self._selected_tags.discard(tag)
        else:
            self._selected_tags.add(tag)
        self._rebuild_tag_bar()
        self._rebuild_grid()

    def clear_tag_filter(self) -> None:
        if self._selected_tags:
            self._selected_tags.clear()
            self._rebuild_tag_bar()
            self._rebuild_grid()

    def _build_dock(self) -> QWidget:
        self.dock_frame = QWidget()
        self.dock_frame.setObjectName("dock")
        self.dock_frame.setFixedHeight(48)

        dock_layout = QHBoxLayout(self.dock_frame)
        dock_layout.setContentsMargins(15, 6, 15, 6)
        dock_layout.setSpacing(8)

        self.dock_hint = QLabel("Minimized:")
        self.dock_hint.setObjectName("dockHint")
        dock_layout.addWidget(self.dock_hint)

        self.dock_scroll = QScrollArea()
        self.dock_scroll.setObjectName("dockScroll")
        self.dock_scroll.setWidgetResizable(True)
        self.dock_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.dock_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.dock_content = QWidget()
        self.dock_content.setObjectName("dockContent")
        self.dock_layout_inner = QHBoxLayout(self.dock_content)
        self.dock_layout_inner.setContentsMargins(0, 0, 0, 0)
        self.dock_layout_inner.setSpacing(6)
        self.dock_layout_inner.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.dock_scroll.setWidget(self.dock_content)

        dock_layout.addWidget(self.dock_scroll, 1)
        self.dock_frame.setVisible(False)
        return self.dock_frame

    def _install_shortcuts(self) -> None:
        # The receiver is passed positionally: `activated=` works at runtime
        # but is not in Qt's stubs, so the keyword form hides real mistakes
        # from the type checker.
        QShortcut(QKeySequence.StandardKey.New, self, self.create_note)
        QShortcut(QKeySequence.StandardKey.Refresh, self, lambda: self.reload())
        QShortcut(QKeySequence.StandardKey.Find, self, self._focus_search)
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo_delete)
        QShortcut(QKeySequence("Ctrl+E"), self, self.export_notes)
        QShortcut(QKeySequence("Ctrl+T"), self, self.toggle_theme)
        QShortcut(QKeySequence("Ctrl+I"), self, self.show_statistics)
        QShortcut(QKeySequence("Esc"), self, self._clear_filters)

    # ─── Loading ──────────────────────────────────────────────────

    def reload(self, *, restore_dock: bool = False) -> None:
        """Re-read notes from disk and rebuild the view.

        ``restore_dock`` reinstates the minimized dock from the persisted
        ``minimized`` flags; that only happens at startup, since afterwards the
        in-memory dock is the source of truth.
        """
        self._notes = FileManager.load_all()
        self.path_lbl.setText(f"Saved to: {FileManager.directory()}")

        if restore_dock:
            self._minimized_ids = [n.id for n in self._notes if n.minimized]

        # Drop dock entries whose note no longer exists on disk.
        known = {n.id for n in self._notes}
        self._minimized_ids = [nid for nid in self._minimized_ids if nid in known]

        self._rebuild_tag_bar()
        self._rebuild_grid()
        self._rebuild_dock()

    def _on_search_changed(self, _text: str) -> None:
        # Debounced: filtering runs against the in-memory list, and rebuilding
        # the grid on every keystroke is what made search feel sluggish.
        self._search_timer.start()

    def _focus_search(self) -> None:
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _clear_search(self) -> None:
        if self.search_input.text():
            self.search_input.clear()

    def _clear_filters(self) -> None:
        """Escape clears everything narrowing the grid, text and tags alike."""
        self._clear_search()
        self.clear_tag_filter()

    # ─── Grid ─────────────────────────────────────────────────────

    def _column_count(self) -> int:
        """Columns that fit the current viewport, within configured bounds."""
        return columns_for_width(
            self.grid_scroll.viewport().width(),
            MIN_CARD_WIDTH,
            GRID_SPACING,
            GRID_MARGIN,
            MIN_GRID_COLUMNS,
            MAX_GRID_COLUMNS,
        )

    def _clear_grid(self) -> None:
        clear_layout(self.grid_layout)
        for row in range(self.grid_layout.rowCount()):
            self.grid_layout.setRowStretch(row, 0)
        for column in range(self.grid_layout.columnCount()):
            self.grid_layout.setColumnStretch(column, 0)

    def _rebuild_grid(self) -> None:
        if self._shutting_down:
            return

        self._card_timer.stop()  # abandon a stream from a previous rebuild
        self._built_cards = 0
        self._clear_grid()
        columns = self._columns = self._column_count()

        self._visible_notes = filter_notes(
            self._notes, self.search_input.text(), self._selected_tags
        )

        if not self._visible_notes:
            filtering = bool(self.search_input.text().strip() or self._selected_tags)
            message = (
                "No notes match your filter."
                if filtering
                else "No notes yet.\nCreate one with “+ New Note” (Ctrl+N)."
            )
            empty = QLabel(message)
            empty.setObjectName("emptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.grid_layout.addWidget(empty, 0, 0, 1, columns)
            self.grid_layout.setRowStretch(0, 1)
            return

        for column in range(columns):
            self.grid_layout.setColumnStretch(column, 1)
        # Absorb leftover vertical space so cards keep their natural height
        # instead of stretching to fill a sparse grid.
        last_row = (len(self._visible_notes) - 1) // columns
        self.grid_layout.setRowStretch(last_row + 1, 1)

        self._built_cards = 0
        self._add_cards(GRID_FIRST_CHUNK)

    def _add_cards(self, count: int) -> None:
        """Build the next ``count`` cards, then schedule any remainder.

        Building 2,000 cards in one pass blocked the UI for two seconds.
        Streaming them keeps the window responsive; the first chunk always
        overfills the viewport, so nothing looks unfinished.
        """
        columns = max(1, self._columns)
        start = self._built_cards
        end = min(start + count, len(self._visible_notes))

        query = self.search_input.text().strip()
        for index in range(start, end):
            note = self._visible_notes[index]
            card = CardWidget(note, query=query)
            card.open_requested.connect(self.open_note)
            card.delete_requested.connect(self.delete_note)
            card.reorder_requested.connect(self._on_reorder)
            self.grid_layout.addWidget(card, index // columns, index % columns)

        self._built_cards = end
        if end < len(self._visible_notes):
            self._card_timer.start()

    def _add_next_chunk(self) -> None:
        if not self._shutting_down:
            self._add_cards(GRID_CHUNK_SIZE)

    def finish_building_grid(self) -> None:
        """Build every remaining card immediately.

        For tests and for anything that needs the full grid without waiting
        on the event loop.
        """
        self._card_timer.stop()
        remaining = len(self._visible_notes) - self._built_cards
        if remaining > 0:
            self._add_cards(remaining)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._shutting_down and self._column_count() != self._columns:
            self._relayout_timer.start()

    # ─── Dock ─────────────────────────────────────────────────────

    def _rebuild_dock(self) -> None:
        clear_layout(self.dock_layout_inner)

        by_id = {n.id: n for n in self._notes}
        shown = 0
        for note_id in self._minimized_ids:
            note = by_id.get(note_id) or FileManager.load_by_id(note_id)
            if note is None:
                continue
            scheme = color_scheme(note.color)
            label = note.title or "Untitled"
            btn = QPushButton(f"📝 {label}")
            btn.setFixedWidth(150)
            btn.setToolTip(f"Restore “{label}”")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {scheme['accent']}; color: #232323;
                    border: none; border-radius: 6px; font-size: 11px; padding: 5px 8px;
                    text-align: left;
                }}
                QPushButton:hover {{ background-color: {scheme['bg']}; }}
            """)
            btn.clicked.connect(lambda _checked=False, nid=note_id: self.restore_note(nid))
            self.dock_layout_inner.addWidget(btn)
            shown += 1

        self.dock_frame.setVisible(shown > 0)

    # ─── Note window lifecycle ────────────────────────────────────

    def _live_widget(self, note_id: str) -> NoteWidget | None:
        """Return the open window for ``note_id``, dropping dead references."""
        widget = live(self._open_notes.get(note_id))
        if widget is None:
            # A destroyed C++ side leaves a stale Python reference that would
            # otherwise linger here forever and crash on next use.
            self._open_notes.pop(note_id, None)
        return widget

    def open_note(self, note_id: str) -> None:
        """Open (or focus) a note in its own floating window."""
        widget = self._live_widget(note_id)
        if widget is not None:
            self._unminimize(note_id)
            widget.show()
            widget.raise_()
            widget.activateWindow()
            return

        note = FileManager.load_by_id(note_id)
        if note is None:
            self._warn(f"Note {note_id} could not be loaded; it may have been deleted.")
            self.reload()
            return

        self._unminimize(note_id, note=note)

        widget = NoteWidget(note, self)
        widget.close_requested.connect(self.close_note)
        widget.minimize_requested.connect(self.minimize_note)
        widget.save_failed.connect(self._on_save_failed)
        widget.content_saved.connect(self._on_content_saved)

        self._open_notes[note_id] = widget
        widget.show()
        widget.raise_()
        widget.activateWindow()

    def close_note(self, note_id: str) -> None:
        """Close a floating note window, flushing pending edits."""
        close_and_delete(self._open_notes.pop(note_id, None))
        if note_id in self._minimized_ids:
            self._minimized_ids.remove(note_id)
        self.reload()

    def minimize_note(self, note_id: str) -> None:
        """Hide a floating note into the dock."""
        widget = self._live_widget(note_id)
        if widget is None:
            return
        try:
            NoteService.set_minimized(widget.note, True)
        except StorageError as exc:
            self._warn(f"Could not save minimized state: {exc}")
        if note_id not in self._minimized_ids:
            self._minimized_ids.append(note_id)
        widget.hide()
        self._sync_note(widget.note)
        self._rebuild_dock()
        self._rebuild_grid()

    def restore_note(self, note_id: str) -> None:
        """Bring a minimized note back from the dock."""
        self.open_note(note_id)

    def _unminimize(self, note_id: str, note: Note | None = None) -> None:
        """Clear the minimized flag in memory, on disk, and in the dock."""
        was_docked = note_id in self._minimized_ids
        if was_docked:
            self._minimized_ids.remove(note_id)

        target = note
        if target is None:
            widget = self._open_notes.get(note_id)
            target = widget.note if widget is not None else None

        changed = False
        if target is not None and target.minimized:
            try:
                changed = NoteService.set_minimized(target, False)
            except StorageError as exc:
                self._warn(f"Could not clear minimized state: {exc}")

        if was_docked:
            self._rebuild_dock()
        if changed:
            self._sync_note(target)
            self._rebuild_grid()

    def create_note(self) -> None:
        """Create a new note and open it."""
        try:
            note = NoteService.create()
        except StorageError as exc:
            self._warn(f"Could not create note: {exc}")
            return
        self._clear_search()
        self.reload()
        self.open_note(note.id)
        self.statusBar().showMessage(f"Created note {note.id}", 3000)

    def delete_note(self, note_id: str) -> None:
        """Delete a note after confirmation."""
        note = next((n for n in self._notes if n.id == note_id), None) or FileManager.load_by_id(
            note_id
        )
        if note is None:
            self.reload()
            return

        reply = QMessageBox.question(
            self,
            "Delete Note",
            f"Move “{note.title or 'Untitled'}” to the trash?\n\n"
            "Nothing is erased: the note file moves to the trash folder and "
            "stays there until you remove it yourself. Ctrl+Z brings it back.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Tear the window down first: a widget left in _open_notes would keep
        # auto-saving the note straight back onto disk after deletion.
        close_and_delete(self._open_notes.pop(note_id, None), silence_signals=True)
        if note_id in self._minimized_ids:
            self._minimized_ids.remove(note_id)

        try:
            self._undo_stack.append(NoteService.delete(note))
        except StorageError as exc:
            self._warn(f"Could not delete note: {exc}")

        self.reload()
        self.statusBar().showMessage(
            f"Moved “{note.title or 'Untitled'}” to the trash — Ctrl+Z to undo", 8000
        )

    def show_statistics(self) -> None:
        """Open the read-only statistics summary."""
        from notsucky.services.statistics import compute
        from notsucky.views.stats_dialog import StatsDialog

        stats = compute(
            self._notes,
            trash_count=len(FileManager.list_trash()),
            backup_count=len(backup.list_backups()),
        )
        StatsDialog(stats, self).exec()

    def export_notes(self) -> None:
        """Export every note as Markdown into a folder the user picks."""
        from notsucky.services import export as export_service

        if not self._notes:
            self.statusBar().showMessage("Nothing to export", 3000)
            return

        directory = QFileDialog.getExistingDirectory(
            self, "Export all notes as Markdown", str(Path.home())
        )
        if not directory:
            return  # cancelled

        try:
            written = export_service.export_all(Path(directory), "md")
        except OSError as exc:
            self._warn(f"Export failed: {exc}")
            return
        self.statusBar().showMessage(
            f"Exported {len(written)} note{'s' if len(written) != 1 else ''} to {directory}",
            8000,
        )

    def undo_delete(self) -> None:
        """Restore the most recently deleted note."""
        while self._undo_stack:
            trash_path = self._undo_stack.pop()
            if trash_path is None:
                continue
            try:
                restored = NoteService.undo_delete(trash_path)
            except StorageError as exc:
                self._warn(f"Could not restore the note: {exc}")
                return
            if restored is None:
                continue
            self.reload()
            self.statusBar().showMessage(
                f"Restored “{restored.title or 'Untitled'}”", 5000
            )
            return
        self.statusBar().showMessage("Nothing to undo", 3000)

    # ─── Reordering ───────────────────────────────────────────────

    def _on_reorder(self, source_id: str, target_id: str) -> None:
        """Persist a drag-to-reorder within the currently visible notes."""
        if self.search_input.text().strip():
            # Reordering a filtered subset would write positions that make no
            # sense once the filter is cleared.
            self.statusBar().showMessage("Clear the filter to reorder notes", 4000)
            return
        try:
            changed = NoteService.reorder(self._visible_notes, source_id, target_id)
        except StorageError as exc:
            self._warn(f"Could not save the new order: {exc}")
            return
        if changed:
            self._notes = sort_for_display(self._notes)
            self._rebuild_grid()

    # ─── Saving ───────────────────────────────────────────────────

    def _sync_note(self, note: Note | None) -> None:
        """Replace the cached copy of ``note`` with the live object."""
        if note is None:
            return
        for index, cached in enumerate(self._notes):
            if cached.id == note.id:
                self._notes[index] = note
                return
        self._notes.append(note)

    def _on_content_saved(self, note_id: str) -> None:
        widget = self._live_widget(note_id)
        if widget is not None:
            self._sync_note(widget.note)
            self._rebuild_grid()

    def _on_save_failed(self, note_id: str, message: str) -> None:
        self._warn(f"Note {note_id} could not be saved: {message}")

    def _auto_save_loop(self) -> None:
        """Safety net for edits that never triggered a debounce flush."""
        for note_id in list(self._open_notes):
            widget = self._live_widget(note_id)
            if widget is None:
                continue
            try:
                widget.flush()
            except Exception:
                logger.exception("Auto-save failed for note %s", note_id)

    def _warn(self, message: str) -> None:
        logger.warning(message)
        self.statusBar().showMessage(f"⚠ {message}", 8000)

    # ─── Shutdown ─────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        """Flush and close every open note before the app exits.

        Note windows are top-level Qt.Tool windows, so without this they would
        keep the process alive and their unsaved edits would be lost.
        """
        self._shutting_down = True
        self._auto_save_timer.stop()
        self._search_timer.stop()
        self._relayout_timer.stop()
        self._card_timer.stop()

        for note_id in list(self._open_notes):
            widget = self._open_notes.pop(note_id)
            try:
                widget.flush()
                close_and_delete(widget)
            except (RuntimeError, StorageError) as exc:
                logger.error("Could not cleanly close note %s: %s", note_id, exc)

        super().closeEvent(event)
