"""The application icon, drawn rather than shipped.

Generating the icon avoids a binary asset in the repository and a package-data
entry in the build, and it stays crisp because each size is drawn at its own
resolution instead of being scaled from one bitmap.

The mark is a sticky note with a folded corner and three ruled lines, in the
application's default note colour.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from notsucky.utils.constants import COLORS, DEFAULT_COLOR_NAME

#: Sizes Windows, macOS, and Linux ask for between them.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _draw(size: int) -> QPixmap:
    """Render the mark at ``size`` x ``size`` pixels."""
    scheme = COLORS[DEFAULT_COLOR_NAME]
    body = QColor(scheme["bg"])
    accent = QColor(scheme["accent"])
    ink = QColor(scheme["fg"])

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    unit = size / 32.0
    margin = 3 * unit
    fold = 9 * unit
    right = size - margin
    bottom = size - margin
    radius = 2 * unit

    # Note body: a rounded rectangle with the bottom-right corner cut away.
    page = QPainterPath()
    page.moveTo(margin + radius, margin)
    page.lineTo(right, margin)
    page.lineTo(right, bottom - fold)
    page.lineTo(right - fold, bottom)
    page.lineTo(margin + radius, bottom)
    page.quadTo(QPointF(margin, bottom), QPointF(margin, bottom - radius))
    page.lineTo(margin, margin + radius)
    page.quadTo(QPointF(margin, margin), QPointF(margin + radius, margin))
    page.closeSubpath()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(body))
    painter.drawPath(page)

    # Header band, clipped to the page so it inherits the rounded corners.
    painter.save()
    painter.setClipPath(page)
    painter.setBrush(QBrush(accent))
    painter.drawRect(QRectF(margin, margin, right - margin, 6 * unit))
    painter.restore()

    # The folded corner, drawn darker so it reads as a turned-up flap.
    flap = QPainterPath()
    flap.moveTo(right, bottom - fold)
    flap.lineTo(right - fold, bottom)
    flap.lineTo(right - fold, bottom - fold)
    flap.closeSubpath()
    painter.setBrush(QBrush(accent.darker(115)))
    painter.drawPath(flap)

    # Ruled lines. Below ~24px they turn to mud, so they are dropped.
    if size >= 24:
        pen = QPen(ink)
        pen.setWidthF(max(1.0, 1.4 * unit))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setOpacity(0.55)
        for index, width_units in enumerate((16, 16, 10)):
            y = margin + (12 + index * 5) * unit
            painter.drawLine(
                QPointF(margin + 4 * unit, y),
                QPointF(margin + (4 + width_units) * unit, y),
            )

    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """Build the multi-resolution application icon.

    Requires a running QGuiApplication, since it rasterises pixmaps.
    """
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(_draw(size))
    return icon
