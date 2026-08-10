"""Small helpers for Qt's Python/C++ object lifetime split.

A PySide object stays alive on the Python side after Qt has deleted the C++
object behind it. Touching one then raises ``RuntimeError: Internal C++ object
already deleted`` — from arbitrary places, including timer callbacks that fire
after a window closed. These helpers keep that handling in one place rather
than scattering identical ``try/except RuntimeError`` blocks.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=QObject)


def is_alive(obj: QObject | None) -> bool:
    """Whether ``obj``'s underlying C++ object still exists."""
    if obj is None:
        return False
    try:
        obj.objectName()
    except RuntimeError:
        return False
    return True


def live(obj: T | None) -> T | None:
    """Return ``obj`` if its C++ side is alive, otherwise None."""
    return obj if is_alive(obj) else None


def close_and_delete(widget: QWidget | None, *, silence_signals: bool = False) -> None:
    """Close a widget and schedule deletion, tolerating an already-dead one.

    ``silence_signals`` blocks the widget's signals first — needed when
    tearing down a note that is being deleted, since a parting ``flush``
    would otherwise write the note straight back to disk.
    """
    if widget is None:
        return
    try:
        if silence_signals:
            widget.blockSignals(True)
            widget.hide()
        widget.close()
        widget.deleteLater()
    except RuntimeError:
        logger.debug("Widget was already destroyed before teardown")
