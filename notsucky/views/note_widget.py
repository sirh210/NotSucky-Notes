"""Individual floating note window."""

from __future__ import annotations

import contextlib
import logging

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollBar,
    QSizeGrip,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from notsucky.models.note import Note
from notsucky.services.file_manager import StorageError
from notsucky.services.note_service import NoteService
from notsucky.utils.constants import (
    COLORS,
    DEBOUNCE_SAVE_DELAY_MS,
    MAX_CONTENT_LENGTH,
    MAX_TITLE_LENGTH,
    MIN_NOTE_HEIGHT,
    MIN_NOTE_WIDTH,
    color_scheme,
)
from notsucky.utils.geometry import cascade_position, clamp_to_screens
from notsucky.views.qt_support import is_alive

logger = logging.getLogger(__name__)

#: Widgets that own their own mouse handling; pressing one must not drag the
#: window out from under the user.
_INTERACTIVE_WIDGETS = (
    QAbstractButton,
    QAbstractScrollArea,
    QLineEdit,
    QScrollBar,
    QSizeGrip,
)


def available_screen_rects() -> list[tuple[int, int, int, int]]:
    """Available geometry of every attached screen, as plain tuples."""
    rects = []
    for screen in QGuiApplication.screens():
        geo = screen.availableGeometry()
        rects.append((geo.x(), geo.y(), geo.width(), geo.height()))
    return rects


class ColorDot(QPushButton):
    """A small circular color swatch in the note's title bar."""

    def __init__(self, name: str, hex_color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color_name = name
        self._hex = hex_color
        self.setFixedSize(14, 14)
        self.setFlat(True)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Change color to {name}")
        self.setAccessibleName(f"{name} color")

    def set_selected(self, selected: bool) -> None:
        self.setChecked(selected)
        border = "2px solid #222" if selected else "1px solid rgba(0, 0, 0, 0.35)"
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._hex}; border-radius: 7px;"
            f" border: {border}; }}"
            "QPushButton:hover { border: 2px solid #222; }"
        )


class NoteWidget(QWidget):
    """A floating, draggable, resizable note window."""

    close_requested = Signal(str)
    minimize_requested = Signal(str)
    save_failed = Signal(str, str)   # note id, message
    content_saved = Signal(str)      # note id

    def __init__(self, note: Note, parent: QWidget | None = None) -> None:
        # Deliberately parentless at the Qt level: a Qt.Tool window parented to
        # the dashboard would always sit above it and could not be stacked
        # independently. The dashboard keeps its own Python reference.
        super().__init__()
        self.note = note
        self._dashboard = parent
        self._drag_offset: QPoint | None = None
        self._closing = False

        # Growth ceilings, never shrink ceilings. A note that already holds
        # more than the limit keeps its current length as its ceiling, so
        # nothing the user wrote is ever discarded by opening the window.
        self._content_ceiling = max(MAX_CONTENT_LENGTH, len(note.content))
        self._title_ceiling = max(MAX_TITLE_LENGTH, len(note.title))

        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(note.title or "Untitled note")
        self.setMinimumSize(MIN_NOTE_WIDTH, MIN_NOTE_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        # QWidget subclasses ignore their own stylesheet background unless
        # styled backgrounds are switched on explicitly.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Debounced writer: restarted on each keystroke, so a burst of typing
        # produces exactly one save instead of one per character.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(DEBOUNCE_SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.flush)

        self._build_ui()
        self._apply_scheme(color_scheme(note.color))
        self._restore_geometry()
        self._install_shortcuts()

    # ─── Construction ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        self.title_bar = self._build_title_bar()
        main.addWidget(self.title_bar)

        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(self.note.content)
        self.text_edit.setAcceptRichText(False)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.text_edit.setAccessibleName("Note content")
        self.text_edit.textChanged.connect(self._on_text_changed)
        main.addWidget(self.text_edit, stretch=1)

        self.status_bar = self._build_status_bar()
        main.addWidget(self.status_bar)

    def _build_title_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("titleBar")
        bar.setFixedHeight(34)
        bar.setCursor(Qt.CursorShape.SizeAllCursor)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        # The title field stretches across the bar, so without an explicit
        # handle there is almost no chrome left to grab the window by.
        self.drag_handle = QLabel("⠿")
        self.drag_handle.setObjectName("dragHandle")
        self.drag_handle.setFixedWidth(14)
        self.drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self.drag_handle.setToolTip("Drag to move this note")
        self.drag_handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.drag_handle)

        self.title_input = QLineEdit(self.note.title)
        self.title_input.setPlaceholderText("Untitled")
        self.title_input.setAccessibleName("Note title")
        # setMaxLength truncates text already in the field, so the ceiling has
        # to allow for a title that is longer than the limit to begin with.
        self.title_input.setMaxLength(self._title_ceiling)
        self.title_input.textChanged.connect(self._on_title_changed)
        layout.addWidget(self.title_input, stretch=1)

        self._dots: list[ColorDot] = []
        for name, scheme in COLORS.items():
            dot = ColorDot(name, scheme["bg"], bar)
            dot.clicked.connect(lambda _checked=False, c=name: self.change_color(c))
            self._dots.append(dot)
            layout.addWidget(dot)

        layout.addSpacing(6)

        min_btn = QPushButton("─")
        min_btn.setFixedSize(24, 24)
        min_btn.setObjectName("minBtn")
        min_btn.setToolTip("Minimize to dock (Ctrl+M)")
        min_btn.setAccessibleName("Minimize note")
        min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        min_btn.clicked.connect(self._request_minimize)
        layout.addWidget(min_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setObjectName("closeBtn")
        close_btn.setToolTip("Close note (Ctrl+W)")
        close_btn.setAccessibleName("Close note")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self._request_close)
        layout.addWidget(close_btn)

        return bar

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("statusBar")
        bar.setFixedHeight(22)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 2, 0)
        layout.setSpacing(4)

        self.status_label = QLabel(self._char_count_text())
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        # Frameless windows get no native resize border; the grip restores it.
        grip = QSizeGrip(bar)
        grip.setToolTip("Drag to resize")
        layout.addWidget(grip, alignment=Qt.AlignmentFlag.AlignBottom)

        return bar

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+W"), self, self._request_close)
        QShortcut(QKeySequence("Ctrl+M"), self, self._request_minimize)
        QShortcut(QKeySequence.StandardKey.Save, self, self.flush)

    # ─── Geometry ─────────────────────────────────────────────────

    def _restore_geometry(self) -> None:
        """Restore size and position, forcing the window back on-screen."""
        screens = available_screen_rects()
        width = max(MIN_NOTE_WIDTH, self.note.width)
        height = max(MIN_NOTE_HEIGHT, self.note.height)
        self.resize(width, height)

        if self.note.x is None or self.note.y is None:
            x, y = cascade_position(self.note.id, width, height, screens)
        else:
            x, y = clamp_to_screens(self.note.x, self.note.y, width, height, screens)
        self.move(x, y)

    def _persist_geometry(self) -> None:
        try:
            NoteService.update_geometry(
                self.note, self.x(), self.y(), self.width(), self.height()
            )
        except StorageError as exc:
            self._report_failure(exc)

    # ─── Dragging ─────────────────────────────────────────────────

    def _is_drag_handle(self, position) -> bool:
        """Whether a press at ``position`` should move the window.

        Inert chrome (the title bar, the status bar, their labels) drags the
        window; interactive controls do not. Walking up from the child under
        the cursor is what catches the editor, whose presses land on its
        viewport rather than on the QTextEdit itself.

        A plain ``childAt(...) is None`` test — which is what v1.0 used — gets
        this exactly backwards and leaves the window undraggable, since the
        title bar it should be dragged by *is* a child.
        """
        child = self.childAt(position)
        while child is not None and child is not self:
            if isinstance(child, _INTERACTIVE_WIDGETS):
                return False
            child = child.parentWidget()
        return True

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_drag_handle(
            event.position().toPoint()
        ):
            # Anchor on the offset between cursor and window origin. Storing
            # the raw cursor position instead makes each move event apply a
            # delta measured from the original press, which compounds.
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        self.move(event.globalPosition().toPoint() - self._drag_offset)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            x, y = clamp_to_screens(
                self.x(), self.y(), self.width(), self.height(), available_screen_rects()
            )
            self.move(x, y)
            self._persist_geometry()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible() and not self._closing:
            # Coalesced through the same debounce as text edits.
            self._save_timer.start()

    # ─── Editing ──────────────────────────────────────────────────

    def _char_count_text(self) -> str:
        count = len(self.note.content)
        return f"{count:,} char{'s' if count != 1 else ''}"

    def _on_title_changed(self, text: str) -> None:
        self.setWindowTitle(text or "Untitled note")
        self._save_timer.start()

    def _on_text_changed(self) -> None:
        text = self.text_edit.toPlainText()
        if len(text) > self._content_ceiling:
            # Refuse the *growth* past the ceiling; never shorten what was
            # already there. The ceiling starts at whatever the note already
            # contained, so opening a very long note cannot shrink it — that
            # would be written back by the next save as a silent deletion.
            cursor = self.text_edit.textCursor()
            position = cursor.position()
            self.text_edit.blockSignals(True)
            self.text_edit.setPlainText(text[: self._content_ceiling])
            cursor.setPosition(min(position, self._content_ceiling))
            self.text_edit.setTextCursor(cursor)
            self.text_edit.blockSignals(False)
            text = self.text_edit.toPlainText()
            self.status_label.setText(f"⚠ limit reached ({self._content_ceiling:,} chars)")
            self._save_timer.start()
            return
        self.status_label.setText(f"{len(text):,} char{'s' if len(text) != 1 else ''}")
        self._save_timer.start()

    def flush(self) -> bool:
        """Write any pending edits immediately. Returns True on success."""
        self._save_timer.stop()
        if not self._widget_alive():
            return False
        try:
            changed = NoteService.update_title(self.note, self.title_input.text())
            changed |= NoteService.update_content(self.note, self.text_edit.toPlainText())
            changed |= NoteService.update_geometry(
                self.note, self.x(), self.y(), self.width(), self.height()
            )
        except StorageError as exc:
            self._report_failure(exc)
            return False
        if changed:
            self.status_label.setText(self._char_count_text())
            self.content_saved.emit(self.note.id)
        return True

    def _widget_alive(self) -> bool:
        """False once Qt has destroyed the underlying C++ objects."""
        return is_alive(self.text_edit)

    def change_color(self, color_name: str) -> None:
        """Switch palette and persist the choice."""
        try:
            NoteService.change_color(self.note, color_name)
        except StorageError as exc:
            self._report_failure(exc)
            return
        self._apply_scheme(color_scheme(self.note.color))

    def _report_failure(self, exc: Exception) -> None:
        logger.error("Note %s could not be saved: %s", self.note.id, exc)
        self.save_failed.emit(self.note.id, str(exc))
        # The widget may already be destroyed when a shutdown flush fails.
        with contextlib.suppress(RuntimeError):
            self.status_label.setText("⚠ not saved")

    # ─── Appearance ───────────────────────────────────────────────

    def _apply_scheme(self, scheme: dict[str, str]) -> None:
        self.setStyleSheet(f"""
            NoteWidget {{ background-color: {scheme['bg']}; border-radius: 8px; }}
            QWidget#titleBar {{
                background-color: {scheme['accent']};
                border-top-left-radius: 8px; border-top-right-radius: 8px;
            }}
            QWidget#statusBar {{
                background-color: {scheme['accent']};
                border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;
            }}
            QTextEdit {{
                background-color: {scheme['bg']}; border: none; padding: 6px;
                font-family: 'Segoe UI', 'Helvetica Neue', sans-serif; font-size: 14px;
                color: {scheme['fg']};
            }}
            QLineEdit {{
                background: transparent; border: none; color: #232323; font-weight: bold;
            }}
            QLabel#statusLabel {{ color: #3A3A3A; font-size: 10px; }}
            QLabel#dragHandle {{ color: rgba(0, 0, 0, 0.45); font-size: 13px; }}
            QPushButton#minBtn, QPushButton#closeBtn {{
                background: transparent; border: none; border-radius: 4px;
                color: #232323; font-size: 14px;
            }}
            QPushButton#minBtn:hover {{ background: rgba(0, 0, 0, 0.12); }}
            QPushButton#closeBtn:hover {{ background: #C0392B; color: white; }}
        """)
        for dot in self._dots:
            dot.set_selected(dot.color_name == self.note.color)

    # ─── Lifecycle ────────────────────────────────────────────────

    def _request_minimize(self) -> None:
        self.flush()
        self.minimize_requested.emit(self.note.id)

    def _request_close(self) -> None:
        self.close_requested.emit(self.note.id)

    def closeEvent(self, event) -> None:
        """Never lose the last edit: flush before the window goes away."""
        self._closing = True
        self.flush()
        super().closeEvent(event)

    def hideEvent(self, event) -> None:
        if not self._closing:
            self.flush()
        super().hideEvent(event)
