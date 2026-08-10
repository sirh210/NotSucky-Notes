"""Grid card widget for dashboard display.

Each card is both a drag source and a drop target: dragging one card onto
another asks the dashboard to move the first into the second's slot.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from notsucky.utils.constants import (
    CARD_PREVIEW_LENGTH,
    MIN_CARD_HEIGHT,
    MIN_CARD_WIDTH,
    NOTE_MIME_TYPE,
    color_scheme,
)

if TYPE_CHECKING:
    from notsucky.models.note import Note

logger = logging.getLogger(__name__)


def format_relative(timestamp: str) -> str:
    """Render an ISO timestamp as a short human-readable age."""
    try:
        moment = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return "unknown"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    seconds = (datetime.now(timezone.utc) - moment).total_seconds()
    if seconds < 0:
        return "just now"
    for limit, divisor, unit in (
        (60, 1, "s"),
        (3600, 60, "m"),
        (86400, 3600, "h"),
        (2592000, 86400, "d"),
    ):
        if seconds < limit:
            value = int(seconds // divisor)
            return "just now" if value == 0 else f"{value}{unit} ago"
    return moment.astimezone().strftime("%Y-%m-%d")


class CardWidget(QWidget):
    """A card representing a note in the dashboard grid."""

    open_requested = Signal(str)                 # note id
    delete_requested = Signal(str)               # note id
    reorder_requested = Signal(str, str)         # source id, target id

    def __init__(self, note: Note, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.note = note
        self._press_pos = None
        self._drop_active = False

        scheme = color_scheme(note.color)
        self._scheme = scheme

        # Without this, a QWidget *subclass* silently ignores the
        # background-color in its own stylesheet and renders transparent.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(MIN_CARD_WIDTH, MIN_CARD_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Double-click to open · drag onto another card to reorder")
        self.setAcceptDrops(True)
        self._apply_style()

        # ─── Layout ───────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 6)
        layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(4)

        title_lbl = QLabel(note.title or "Untitled")
        title_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {scheme['fg']}; background: transparent;"
        )
        title_lbl.setWordWrap(True)
        title_row.addWidget(title_lbl, stretch=1)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(20, 20)
        del_btn.setToolTip("Delete this note")
        del_btn.setAccessibleName(f"Delete note {note.title or 'Untitled'}")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #8B2E24; font-size: 13px;"
            " border: none; border-radius: 10px; }"
            "QPushButton:hover { background: rgba(192, 57, 43, 0.18); color: #C0392B; }"
        )
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.note.id))
        title_row.addWidget(del_btn, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(title_row)

        # Preview
        preview = " ".join(note.content.split())
        if len(preview) > CARD_PREVIEW_LENGTH:
            preview = preview[:CARD_PREVIEW_LENGTH].rstrip() + "…"
        preview_lbl = QLabel(preview or "(empty)")
        preview_lbl.setWordWrap(True)
        preview_lbl.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        preview_lbl.setStyleSheet(
            f"font-size: 11px; color: {scheme['fg']}; background: transparent;"
        )
        layout.addWidget(preview_lbl, stretch=1)

        # Meta row
        chars = len(note.content)
        meta = f"{chars} char{'s' if chars != 1 else ''} · {format_relative(note.updated_at)}"
        if note.minimized:
            meta += " · minimized"
        status_lbl = QLabel(meta)
        status_lbl.setStyleSheet(
            f"font-size: 9px; color: {scheme['fg']}; background: transparent;"
        )
        status_lbl.setEnabled(False)  # renders muted without hard-coding a grey
        layout.addWidget(status_lbl)

    # ─── Styling ──────────────────────────────────────────────────

    def _apply_style(self) -> None:
        border = (
            f"2px dashed {self._scheme['accent']}" if self._drop_active else "2px solid transparent"
        )
        self.setStyleSheet(
            f"CardWidget {{ background-color: {self._scheme['bg']};"
            f" border-radius: 8px; border: {border}; }}"
        )

    def _set_drop_active(self, active: bool) -> None:
        if active != self._drop_active:
            self._drop_active = active
            self._apply_style()

    # ─── Opening ──────────────────────────────────────────────────

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_requested.emit(self.note.id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        """Enter opens the focused card, so the grid is keyboard-navigable."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_requested.emit(self.note.id)
            event.accept()
            return
        super().keyPressEvent(event)

    # ─── Drag source ──────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        travelled = (event.position().toPoint() - self._press_pos).manhattanLength()
        if travelled < QApplication.startDragDistance():
            return

        self._press_pos = None
        mime = QMimeData()
        mime.setData(NOTE_MIME_TYPE, self.note.id.encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(event.position().toPoint())
        drag.exec(Qt.DropAction.MoveAction)

    # ─── Drop target ──────────────────────────────────────────────

    @staticmethod
    def _dragged_id(event) -> str | None:
        mime = event.mimeData()
        if not mime.hasFormat(NOTE_MIME_TYPE):
            return None
        return bytes(mime.data(NOTE_MIME_TYPE)).decode("utf-8", errors="replace")

    def dragEnterEvent(self, event) -> None:
        source_id = self._dragged_id(event)
        if source_id is None or source_id == self.note.id:
            event.ignore()
            return
        self._set_drop_active(True)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._set_drop_active(False)
        source_id = self._dragged_id(event)
        if source_id is None or source_id == self.note.id:
            event.ignore()
            return
        event.acceptProposedAction()
        self.reorder_requested.emit(source_id, self.note.id)
