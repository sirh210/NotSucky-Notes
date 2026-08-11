"""The statistics dialog.

Two deliberate choices about how the numbers are drawn:

**The colour breakdown is not colour-coded.** The obvious design paints each
bar in its note colour, and it fails: run as a categorical palette, the six
pastels miss the lightness band and the chroma floor, sit at 1.0-1.6:1 against
any surface, and - the disqualifying one - put blue and green 8.0 dE apart for
*normal* vision, where the floor is 15. Those hues cannot be re-stepped
because they are the product's note colours. So the bars carry no identity:
they are one hue, and a swatch plus a written name carries recognition.

**Everything is one series.** Nothing here needs a legend, so nothing has one;
the section heading names the measure and the values are written beside the
marks. The plain-text report in ``services.statistics`` is the table view.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from notsucky.services.statistics import Statistics
from notsucky.utils.constants import COLORS, DEFAULT_COLOR_NAME
from notsucky.utils.theme import current_theme, palette

#: One hue per theme for every mark, contrast-checked against that theme's
#: panel: 8.35:1 on dark, 4.93:1 on light. WCAG 1.4.11 asks 3:1 for a
#: graphical object that carries meaning.
BAR_HUE = {"dark": "#6FCB84", "light": "#2F6B3A"}

#: Grid and axis lines are meant to recede; they carry no data.
GRID_HUE = {"dark": "#4A4A50", "light": "#B8B4AA"}

BAR_RADIUS = 4.0   # rounded data-end
BAR_GAP = 2.0      # surface gap between adjacent marks


def _hues() -> tuple[QColor, QColor]:
    name = current_theme()
    return QColor(BAR_HUE.get(name, BAR_HUE["dark"])), QColor(
        GRID_HUE.get(name, GRID_HUE["dark"])
    )


class ActivityChart(QWidget):
    """Edits per day over the recent window, as columns.

    A single series over time: no legend, a recessive baseline, and only the
    peak is labelled — a number over every column is noise, not information.
    """

    def __init__(self, activity: list[tuple[date, int, int]], parent=None) -> None:
        super().__init__(parent)
        self.activity = activity
        self.peak = max((updated for _d, _c, updated in activity), default=0)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Edits per day, most recent last")
        if activity:
            self.setToolTip(
                "\n".join(
                    f"{day.isoformat()}: {updated} edit{'s' if updated != 1 else ''}"
                    for day, _created, updated in activity
                )
            )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bar_hue, grid_hue = _hues()
        muted = QColor(palette()["text_muted"])

        label_band = 16.0
        plot_height = max(1.0, self.height() - label_band - 4.0)
        count = max(1, len(self.activity))
        slot = self.width() / count
        bar_width = max(2.0, slot - BAR_GAP)

        # Baseline: present so the bars are anchored, recessive so it is not
        # read as data.
        painter.setPen(QPen(grid_hue, 1))
        baseline = plot_height + 1.0
        painter.drawLine(0, int(baseline), self.width(), int(baseline))

        if self.peak == 0:
            painter.setPen(QPen(muted, 1))
            font = painter.font()
            font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
            painter.setFont(font)
            painter.drawText(
                QRectF(0, 0, self.width(), plot_height),
                Qt.AlignmentFlag.AlignCenter,
                "No edits in this window",
            )
            painter.end()
            return

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bar_hue)
        peak_index = max(
            range(len(self.activity)), key=lambda i: self.activity[i][2]
        )

        for index, (_day, _created, updated) in enumerate(self.activity):
            if not updated:
                continue
            height = (updated / self.peak) * (plot_height - 12.0)
            rect = QRectF(
                index * slot + BAR_GAP / 2,
                baseline - height,
                bar_width,
                height,
            )
            # Rounded data-end, square against the baseline: clip the bottom
            # half of the rounding by overdrawing a plain rect.
            painter.drawRoundedRect(rect, BAR_RADIUS, BAR_RADIUS)
            if height > BAR_RADIUS:
                painter.drawRect(
                    QRectF(rect.x(), rect.y() + BAR_RADIUS, rect.width(),
                           height - BAR_RADIUS)
                )

        # Selective direct label: the peak only.
        font = QFont(painter.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(palette()["text"]), 1))
        peak_value = self.activity[peak_index][2]
        peak_height = (peak_value / self.peak) * (plot_height - 12.0)
        painter.drawText(
            QRectF(peak_index * slot - slot, baseline - peak_height - 14.0,
                   slot * 3, 12.0),
            Qt.AlignmentFlag.AlignCenter,
            str(peak_value),
        )

        # Only the ends of the window are dated; a label per column collides.
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QPen(muted, 1))
        first, last = self.activity[0][0], self.activity[-1][0]
        painter.drawText(
            QRectF(0, baseline + 2, self.width() / 2, label_band),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            first.strftime("%d %b"),
        )
        painter.drawText(
            QRectF(self.width() / 2, baseline + 2, self.width() / 2, label_band),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "today" if last == date.today() else last.strftime("%d %b"),
        )
        painter.end()


class RankedBars(QWidget):
    """A ranked breakdown: swatch, name, one-hue bar, value.

    The bar length is the encoding. The name is always written, so identity
    never depends on a colour — which matters here because the categories
    *are* colours that cannot be safely distinguished as marks.
    """

    ROW_HEIGHT = 20

    def __init__(
        self,
        rows: list[tuple[str, int]],
        *,
        swatches: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.rows = rows
        self.swatches = swatches
        self.peak = max((value for _label, value in rows), default=0)
        self.setMinimumHeight(max(1, len(rows)) * self.ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(
            "; ".join(f"{label}: {value}" for label, value in rows) or "No data"
        )
        if rows:
            self.setToolTip("\n".join(f"{label}: {value}" for label, value in rows))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bar_hue, _grid = _hues()
        colours = palette()

        font = QFont(painter.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1))
        painter.setFont(font)

        swatch_w = 14.0 if self.swatches else 0.0
        label_w = 74.0
        value_w = 34.0
        bar_x = swatch_w + label_w
        bar_w = max(20.0, self.width() - bar_x - value_w - 6.0)

        for index, (label, value) in enumerate(self.rows):
            top = index * self.ROW_HEIGHT
            centre = QRectF(0, top, self.width(), self.ROW_HEIGHT - BAR_GAP)

            if self.swatches:
                scheme = COLORS.get(label, COLORS[DEFAULT_COLOR_NAME])
                painter.setPen(QPen(QColor(colours["border"]), 1))
                painter.setBrush(QColor(scheme["bg"]))
                # A 2px surface ring keeps a pale swatch from vanishing.
                painter.drawRoundedRect(
                    QRectF(0, top + 4.0, 10.0, 10.0), 2.0, 2.0
                )

            painter.setPen(QPen(QColor(colours["text"]), 1))
            painter.drawText(
                QRectF(swatch_w, centre.y(), label_w - 6.0, centre.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

            if self.peak:
                width = (value / self.peak) * bar_w
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(bar_hue)
                height = centre.height() - 8.0
                rect = QRectF(bar_x, centre.y() + 4.0, max(2.0, width), height)
                painter.drawRoundedRect(rect, BAR_RADIUS, BAR_RADIUS)
                if width > BAR_RADIUS:
                    painter.drawRect(
                        QRectF(rect.x(), rect.y(), width - BAR_RADIUS, height)
                    )

            painter.setPen(QPen(QColor(colours["text_muted"]), 1))
            painter.drawText(
                QRectF(self.width() - value_w, centre.y(), value_w, centre.height()),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value:,}",
            )
        painter.end()


class StatsDialog(QDialog):
    """Read-only summary of the note store."""

    def __init__(self, stats: Statistics, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stats = stats
        self.setWindowTitle("Statistics")
        self.setMinimumSize(520, 560)
        self.resize(600, 680)
        self._apply_theme()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("statsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("statsBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(18)

        layout.addWidget(self._build_tiles())
        layout.addLayout(self._build_headline())
        layout.addWidget(self._section("Edits per day", ActivityChart(stats.activity)))
        layout.addWidget(
            self._section(
                "Notes by colour",
                RankedBars(stats.colors, swatches=True),
                empty="No notes yet",
                has_data=bool(stats.colors),
            )
        )
        layout.addWidget(
            self._section(
                "Most used tags",
                RankedBars(stats.tags),
                empty="No tags yet — add them at the foot of a note",
                has_data=bool(stats.tags),
            )
        )
        layout.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(20, 10, 20, 14)
        hint = QLabel("Same figures without a display: notsucky-notes-cli --stats")
        hint.setObjectName("statsHint")
        footer.addWidget(hint)
        footer.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("statsClose")
        close.setDefault(True)
        close.setFixedSize(88, 30)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        outer.addLayout(footer)

    # ─── Construction helpers ─────────────────────────────────────

    def _apply_theme(self) -> None:
        c = palette()
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c['bg']}; }}
            QWidget#statsBody {{ background-color: {c['bg']}; }}
            QScrollArea#statsScroll {{ background: transparent; border: none; }}
            QFrame#statTile {{
                background-color: {c['panel']}; border: 1px solid {c['border']};
                border-radius: 4px;
            }}
            QLabel#tileValue {{
                color: {c['text']}; font-size: 20px; font-weight: bold;
                background: transparent;
            }}
            QLabel#tileLabel {{
                color: {c['text_muted']}; font-size: 9px; background: transparent;
            }}
            QLabel#sectionTitle {{
                color: {c['text']}; font-size: 11px; font-weight: bold;
                background: transparent;
            }}
            QLabel#headline, QLabel#headlineValue {{
                color: {c['text']}; font-size: 12px; background: transparent;
            }}
            QLabel#headline {{ color: {c['text_muted']}; }}
            QLabel#emptyNote, QLabel#statsHint {{
                color: {c['text_muted']}; font-size: 10px; background: transparent;
            }}
            QPushButton#statsClose {{
                background-color: {c['border']}; color: {c['text']};
                border: none; border-radius: 6px;
            }}
            QPushButton#statsClose:hover {{ background-color: {c['hover']}; }}
        """)

    def _build_tiles(self) -> QWidget:
        """Single magnitudes belong on tiles, not in a chart."""
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        s = self.stats
        tiles = [
            (f"{s.total_notes:,}", "notes"),
            (f"{s.total_words:,}", "words"),
            (f"{s.distinct_tags:,}", "tags in use"),
            (f"{s.average_characters:,}", "average length"),
            (f"{s.trash_count:,}", "in trash"),
            (f"{s.backup_count:,}", "backups"),
        ]
        for index, (value, label) in enumerate(tiles):
            tile = QFrame()
            tile.setObjectName("statTile")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(12, 8, 12, 8)
            tile_layout.setSpacing(0)

            value_lbl = QLabel(value)
            value_lbl.setObjectName("tileValue")
            label_lbl = QLabel(label)
            label_lbl.setObjectName("tileLabel")
            tile_layout.addWidget(value_lbl)
            tile_layout.addWidget(label_lbl)
            tile.setAccessibleName(f"{value} {label}")
            grid.addWidget(tile, index // 3, index % 3)

        return holder

    def _build_headline(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(4)
        s = self.stats

        if s.longest_note is not None:
            layout.addLayout(
                self._fact(
                    "Longest note",
                    f"{s.longest_note.title or 'Untitled'} "
                    f"({len(s.longest_note.content):,} characters)",
                )
            )
        if s.most_used_color:
            layout.addLayout(self._fact("Most used colour", s.most_used_color))
        busiest = s.busiest_day
        if busiest:
            layout.addLayout(
                self._fact(
                    "Busiest day",
                    f"{busiest[0].strftime('%d %b')} — {busiest[1]} edits",
                )
            )
        if s.untagged_notes:
            layout.addLayout(self._fact("Untagged notes", f"{s.untagged_notes:,}"))
        return layout

    @staticmethod
    def _fact(label: str, value: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        name = QLabel(label)
        name.setObjectName("headline")
        name.setFixedWidth(120)
        text = QLabel(value)
        text.setObjectName("headlineValue")
        text.setWordWrap(True)
        row.addWidget(name)
        row.addWidget(text, 1)
        return row

    def _section(
        self, title: str, chart: QWidget, *, empty: str = "", has_data: bool = True
    ) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        if has_data:
            layout.addWidget(chart)
        else:
            note = QLabel(empty)
            note.setObjectName("emptyNote")
            layout.addWidget(note)
        return holder
