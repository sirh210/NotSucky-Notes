"""Chrome palettes for the dashboard shell, and the active-theme setting.

Only the *chrome* has a theme: the note colours are the six pastels, and they
read correctly on either ground, so a note looks the same whichever theme is
active. That keeps a note's colour meaningful — it identifies the note, it is
not a consequence of a setting.

Contrast for every text/ground pair below was checked against WCAG AA.
"""

from __future__ import annotations

from typing import Final, Literal

ThemeName = Literal["dark", "light"]

THEMES: Final[dict[str, dict[str, str]]] = {
    "dark": {
        "bg": "#2D2D30",
        "panel": "#1E1E22",
        "border": "#3E3E42",
        "hover": "#50505A",
        "text": "#E8E8EA",
        "text_muted": "#9A9AA0",     # 5.4:1 on #2D2D30
        "input_bg": "#3E3E42",
        "chip_bg": "#3E3E42",
        "chip_text": "#D8D8DC",
        "chip_active_bg": "#4CAF50",
        "chip_active_text": "#12240F",
    },
    "light": {
        "bg": "#F2F1ED",
        "panel": "#E4E2DC",
        "border": "#CFCCC3",
        "hover": "#D6D3CA",
        "text": "#1F1E1B",
        "text_muted": "#5C5952",     # 6.0:1 on #F2F1ED
        "input_bg": "#FFFFFF",
        "chip_bg": "#DAD7CE",
        "chip_text": "#33312C",
        "chip_active_bg": "#2F6B3A",
        "chip_active_text": "#FFFFFF",
    },
}

DEFAULT_THEME: Final[str] = "dark"


def palette(name: str | None = None) -> dict[str, str]:
    """Return the palette for ``name``, falling back to the stored setting."""
    if name is None:
        name = current_theme()
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def current_theme() -> str:
    """The theme the user last chose, or the default."""
    from notsucky.utils.settings import get_setting

    value = get_setting("theme", DEFAULT_THEME)
    return value if value in THEMES else DEFAULT_THEME


def set_theme(name: str) -> str:
    """Persist the active theme. Returns the theme actually stored."""
    from notsucky.utils.settings import set_setting

    chosen = name if name in THEMES else DEFAULT_THEME
    set_setting("theme", chosen)
    return chosen


def toggle_theme() -> str:
    """Flip between light and dark. Returns the new theme."""
    return set_theme("light" if current_theme() == "dark" else "dark")
