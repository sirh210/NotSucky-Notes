"""Match highlighting for search results.

Kept free of Qt so it can be tested without a display. The output is a small
fragment of rich text, which means the note's own text has to be escaped
first: a note containing ``<b>`` or ``&amp;`` must render as those characters,
not as markup.
"""

from __future__ import annotations

from html import escape

#: Wraps a match. A background rather than a colour change, so the highlight
#: survives on every note colour and does not fight the palette.
OPEN = '<span style="background-color: {accent}; color: #1A1A1A;">'
CLOSE = "</span>"


def find_matches(text: str, query: str) -> list[tuple[int, int]]:
    """Return (start, end) spans of every case-insensitive match.

    Overlapping is impossible because the search advances past each hit.
    An empty or whitespace-only query matches nothing, rather than matching
    everywhere.
    """
    needle = query.strip().lower()
    if not needle or not text:
        return []

    haystack = text.lower()
    spans: list[tuple[int, int]] = []
    start = haystack.find(needle)
    while start != -1:
        spans.append((start, start + len(needle)))
        start = haystack.find(needle, start + len(needle))
    return spans


def highlight(text: str, query: str, accent: str = "#FFD600") -> str:
    """Escape ``text`` and wrap each match of ``query`` in a highlight span.

    Always returns escaped rich text, whether or not anything matched, so
    callers can hand the result straight to a rich-text label without
    deciding which escaping applies.
    """
    spans = find_matches(text, query)
    if not spans:
        return escape(text)

    opening = OPEN.format(accent=accent)
    out: list[str] = []
    cursor = 0
    for start, end in spans:
        out.append(escape(text[cursor:start]))
        out.append(opening)
        out.append(escape(text[start:end]))
        out.append(CLOSE)
        cursor = end
    out.append(escape(text[cursor:]))
    return "".join(out)


def preview_around_match(text: str, query: str, width: int) -> str:
    """Return a ``width``-character window of ``text`` containing the match.

    A match 900 characters into a note is useless if the preview only ever
    shows the first 80, so the window slides to include it and marks the
    elision with an ellipsis.
    """
    flattened = " ".join(text.split())
    if len(flattened) <= width:
        return flattened

    spans = find_matches(flattened, query)
    if not spans:
        return flattened[:width].rstrip() + "…"

    start = spans[0][0]
    if start + len(query.strip()) <= width:
        return flattened[:width].rstrip() + "…"

    # Centre the window on the match, then clamp it to the text.
    begin = max(0, start - width // 3)
    end = min(len(flattened), begin + width)
    begin = max(0, end - width)
    fragment = flattened[begin:end].strip()
    return ("…" if begin > 0 else "") + fragment + ("…" if end < len(flattened) else "")
