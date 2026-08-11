"""Application-wide configuration constants.

Storage locations deliberately live in :mod:`notsucky.utils.paths` instead of
here: a module-level ``NOTES_DIR`` constant gets captured at import time by
every module that imports it, which makes the location impossible to override
after the fact.
"""

from __future__ import annotations

from typing import Final

# ─── Timing ───────────────────────────────────────────────────────
AUTO_SAVE_INTERVAL_MS: Final[int] = 30_000
DEBOUNCE_SAVE_DELAY_MS: Final[int] = 600
SEARCH_DEBOUNCE_MS: Final[int] = 150

# ─── Limits ───────────────────────────────────────────────────────
# These bound how far *new* input may grow a note. They are never applied
# retroactively: content that is already longer — written by an older build,
# by hand, or by another tool — is loaded, displayed, and saved back in full.
# Truncating on load looks harmless and then destroys the note on the next
# save, so a note may only ever lose text because the user deleted it.
MAX_TITLE_LENGTH: Final[int] = 200
MAX_CONTENT_LENGTH: Final[int] = 1_000_000
CARD_PREVIEW_LENGTH: Final[int] = 80

#: Caps on *new* tags. A file already holding more, or longer, keeps them.
MAX_TAG_LENGTH: Final[int] = 30
MAX_TAGS_PER_NOTE: Final[int] = 20
CARD_TAG_LIMIT: Final[int] = 4  # chips shown on a card before "+n"

# ─── Grid ─────────────────────────────────────────────────────────
MIN_CARD_WIDTH: Final[int] = 180
MIN_CARD_HEIGHT: Final[int] = 150
MIN_GRID_COLUMNS: Final[int] = 1
MAX_GRID_COLUMNS: Final[int] = 6
GRID_SPACING: Final[int] = 16
GRID_MARGIN: Final[int] = 20

#: Cards built synchronously before the grid yields to the event loop. Sized
#: to comfortably overfill any viewport, so the first paint is always
#: complete; the rest stream in without freezing the window.
GRID_FIRST_CHUNK: Final[int] = 48

#: Cards built per timer tick after the first chunk.
GRID_CHUNK_SIZE: Final[int] = 32

# ─── Note windows ─────────────────────────────────────────────────
DEFAULT_NOTE_WIDTH: Final[int] = 320
DEFAULT_NOTE_HEIGHT: Final[int] = 280
MIN_NOTE_WIDTH: Final[int] = 220
MIN_NOTE_HEIGHT: Final[int] = 160

# ─── Colors ───────────────────────────────────────────────────────
DEFAULT_COLOR_NAME: Final[str] = "Yellow"

COLORS: Final[dict[str, dict[str, str]]] = {
    "Yellow": {"bg": "#FFF9C4", "fg": "#5D4A00", "accent": "#FFD600"},
    "Green":  {"bg": "#C8E6C9", "fg": "#1B4D1F", "accent": "#4CAF50"},
    "Blue":   {"bg": "#BBDEFB", "fg": "#0D3C75", "accent": "#2196F3"},
    "Pink":   {"bg": "#F8BBD0", "fg": "#7A0E3C", "accent": "#E91E63"},
    "Orange": {"bg": "#FFE0B2", "fg": "#7A3000", "accent": "#FF9800"},
    "Purple": {"bg": "#E1BEE7", "fg": "#4A1264", "accent": "#9C27B0"},
}

# ─── Dark chrome palette (dashboard shell) ────────────────────────
CHROME_BG: Final[str] = "#2D2D30"
CHROME_PANEL: Final[str] = "#1E1E22"
CHROME_BORDER: Final[str] = "#3E3E42"
CHROME_TEXT: Final[str] = "#E8E8EA"
CHROME_TEXT_MUTED: Final[str] = "#9A9AA0"

# ─── Drag & drop ──────────────────────────────────────────────────
NOTE_MIME_TYPE: Final[str] = "application/x-notsucky-note-id"


def color_scheme(name: str | None) -> dict[str, str]:
    """Return the palette for ``name``, falling back to the default color."""
    return COLORS.get(name or "", COLORS[DEFAULT_COLOR_NAME])
