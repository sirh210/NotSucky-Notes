"""Pure geometry helpers, kept free of Qt so they can be unit tested."""

from __future__ import annotations

from collections.abc import Sequence

#: A screen rectangle as ``(x, y, width, height)``.
Rect = tuple[int, int, int, int]


def _overlap_area(a: Rect, b: Rect) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    dx = min(ax + aw, bx + bw) - max(ax, bx)
    dy = min(ay + ah, by + bh) - max(ay, by)
    return dx * dy if dx > 0 and dy > 0 else 0


def columns_for_width(
    viewport_width: int,
    card_width: int,
    spacing: int,
    margin: int,
    minimum: int,
    maximum: int,
) -> int:
    """How many cards of ``card_width`` fit across ``viewport_width``."""
    available = viewport_width - 2 * margin
    if available <= 0:
        return minimum
    fitting = (available + spacing) // (card_width + spacing)
    return max(minimum, min(maximum, int(fitting)))


def clamp_to_screens(
    x: int, y: int, width: int, height: int, screens: Sequence[Rect]
) -> tuple[int, int]:
    """Return a position that keeps a ``width`` x ``height`` window on screen.

    A window is pulled onto whichever screen it already overlaps most; if it
    overlaps none (a saved position from a monitor that is no longer attached,
    or a runaway drag) it lands on the first screen. Windows larger than their
    screen are aligned to the top-left rather than pushed off the other side.
    """
    if not screens:
        return x, y

    window: Rect = (x, y, width, height)
    best = max(screens, key=lambda rect: _overlap_area(window, rect))
    if _overlap_area(window, best) == 0:
        best = screens[0]

    sx, sy, sw, sh = best
    clamped_x = sx if width >= sw else min(max(x, sx), sx + sw - width)
    clamped_y = sy if height >= sh else min(max(y, sy), sy + sh - height)
    return clamped_x, clamped_y


def cascade_position(
    seed: str, width: int, height: int, screens: Sequence[Rect]
) -> tuple[int, int]:
    """Pick a deterministic, on-screen starting position for a new note.

    Derived from ``seed`` (the note id) so a note without a saved position
    reopens in the same place, and offset in a cascade so several new notes do
    not stack exactly on top of each other.
    """
    if not screens:
        return 0, 0
    sx, sy, sw, sh = screens[0]

    # Stable across processes, unlike hash() which is salted per interpreter.
    digest = sum((index + 1) * ord(char) for index, char in enumerate(seed or "note"))
    step = 28
    slots_x = max(1, (sw - width - 80) // step)
    slots_y = max(1, (sh - height - 80) // step)

    x = sx + 40 + (digest % slots_x) * step
    y = sy + 40 + ((digest // max(1, slots_x)) % slots_y) * step
    return clamp_to_screens(x, y, width, height, screens)
