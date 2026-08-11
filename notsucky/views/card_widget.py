"""Grid card widget for dashboard display.

Each card is both a drag source and a drop target: dragging one card onto
another asks the dashboard to move the first into the second's slot.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
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
    COLORS,
    DEFAULT_COLOR_NAME,
    MIN_CARD_HEIGHT,
    MIN_CARD_WIDTH,
    NOTE_MIME_TYPE,
)
from notsucky.utils.highlight import highlight, preview_around_match

if TYPE_CHECKING:
    from notsucky.models.note import Note

logger = logging.getLogger(__name__)


def _build_stylesheet() -> str:
    """One stylesheet covering every card colour, keyed on a property.

    Qt re-parses CSS for every widget that carries its own stylesheet. With
    five ``setStyleSheet`` calls per card that was ~80% of the cost of
    building the grid, so the rules live at application scope instead and
    each card only sets a ``noteColor`` property.
    """
    rules = [
        # Sized and coloured per note; the transparent border reserves the
        # space the drop indicator later fills, so nothing shifts on hover.
        "CardWidget { border-radius: 8px; border: 2px solid transparent; }",
        'CardWidget[dropActive="true"] { border-style: dashed; }',
        "CardWidget QLabel { background: transparent; }",
        "CardWidget QLabel#cardTitle { font-weight: bold; font-size: 13px; }",
        "CardWidget QLabel#cardPreview { font-size: 11px; }",
        "CardWidget QLabel#cardMeta { font-size: 9px; }",
        "CardWidget QPushButton#cardDelete {"
        " background: transparent; color: #8B2E24; font-size: 13px;"
        " border: none; border-radius: 10px; }",
        "CardWidget QPushButton#cardDelete:hover {"
        " background: rgba(192, 57, 43, 0.18); color: #C0392B; }",
    ]
    for name, scheme in COLORS.items():
        selector = f'CardWidget[noteColor="{name}"]'
        rules += [
            f"{selector} {{ background-color: {scheme['bg']}; }}",
            f"{selector}[dropActive=\"true\"] {{ border-color: {scheme['accent']}; }}",
            f"{selector} QLabel {{ color: {scheme['fg']}; }}",
        ]
    return "\n".join(rules)


CARD_STYLESHEET = _build_stylesheet()

_styles_installed = False


def ensure_card_styles() -> None:
    """Install the shared card stylesheet on the application, once.

    Every rule is scoped to ``CardWidget``, so nothing else is affected.
    """
    global _styles_installed
    app = QApplication.instance()
    # instance() is typed as (and can be) a QCoreApplication, which has no
    # stylesheet at all — that is the headless case, where there is nothing
    # to style.
    if _styles_installed or not isinstance(app, QApplication):
        return
    existing = app.styleSheet() or ""
    if CARD_STYLESHEET not in existing:
        app.setStyleSheet(f"{existing}\n{CARD_STYLESHEET}")
    _styles_installed = True


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

    def __init__(
        self, note: Note, parent: QWidget | None = None, query: str = ""
    ) -> None:
        super().__init__(parent)
        ensure_card_styles()
        self.note = note
        self.query = query
        self._press_pos: QPoint | None = None
        self._drop_active = False

        # Without this, a QWidget *subclass* silently ignores the
        # background-color it is given and renders transparent.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("noteColor", note.color if note.color in COLORS else DEFAULT_COLOR_NAME)
        self.setProperty("dropActive", False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(MIN_CARD_WIDTH, MIN_CARD_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Double-click to open · drag onto another card to reorder")
        self.setAcceptDrops(True)

        # ─── Layout ───────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 6)
        layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(4)

        # Titles and previews are rendered as rich text so matches can be
        # marked. The note's own text is escaped by highlight(), so a note
        # containing <b> shows those characters instead of turning bold.
        accent = COLORS.get(note.color, COLORS[DEFAULT_COLOR_NAME])["accent"]
        title_lbl = QLabel(highlight(note.title or "Untitled", query, accent))
        title_lbl.setObjectName("cardTitle")
        title_lbl.setTextFormat(Qt.TextFormat.RichText)
        title_lbl.setWordWrap(True)
        title_row.addWidget(title_lbl, stretch=1)

        del_btn = QPushButton("✕")
        del_btn.setObjectName("cardDelete")
        del_btn.setFixedSize(20, 20)
        del_btn.setToolTip("Delete this note")
        del_btn.setAccessibleName(f"Delete note {note.title or 'Untitled'}")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.note.id))
        title_row.addWidget(del_btn, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(title_row)

        # Preview. The window slides to include the match, because a hit 900
        # characters into a note is invisible if the preview always starts
        # at the beginning.
        preview = preview_around_match(note.content, query, CARD_PREVIEW_LENGTH)
        preview_lbl = QLabel(highlight(preview, query, accent) if preview else "(empty)")
        preview_lbl.setObjectName("cardPreview")
        preview_lbl.setTextFormat(Qt.TextFormat.RichText)
        preview_lbl.setWordWrap(True)
        preview_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(preview_lbl, stretch=1)

        # Meta row
        chars = len(note.content)
        meta = f"{chars} char{'s' if chars != 1 else ''} · {format_relative(note.updated_at)}"
        if note.minimized:
            meta += " · minimized"
        status_lbl = QLabel(meta)
        status_lbl.setObjectName("cardMeta")
        status_lbl.setEnabled(False)  # renders muted without hard-coding a grey
        layout.addWidget(status_lbl)

    # ─── Styling ──────────────────────────────────────────────────

    def _set_drop_active(self, active: bool) -> None:
        """Toggle the drop indicator via a property, not a new stylesheet.

        Qt only re-evaluates property selectors after an unpolish/polish
        round trip, which is still far cheaper than re-parsing CSS.
        """
        if active == self._drop_active:
            return
        self._drop_active = active
        self.setProperty("dropActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

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
