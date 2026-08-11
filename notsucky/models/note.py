"""Data model for a single note."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeGuard

from notsucky.utils.constants import (
    COLORS,
    DEFAULT_COLOR_NAME,
    DEFAULT_NOTE_HEIGHT,
    DEFAULT_NOTE_WIDTH,
    MAX_TAG_LENGTH,
    MIN_NOTE_HEIGHT,
    MIN_NOTE_WIDTH,
)

#: Note ids become file names, so they are restricted to a conservative set of
#: characters. This is what stops a hand-edited or hostile JSON file from
#: writing outside the notes directory via an id like ``../../.bashrc``.
ID_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")

ID_LENGTH = 8


def new_id() -> str:
    """Generate a fresh note id."""
    return uuid.uuid4().hex[:ID_LENGTH]


def utc_now() -> str:
    """Current time as a timezone-aware ISO 8601 string.

    Timestamps are compared and sorted as strings, so they must all be in the
    same zone; naive local timestamps reorder themselves across DST changes.
    """
    return datetime.now(timezone.utc).isoformat()


def is_valid_id(value: Any) -> TypeGuard[str]:
    """Return whether ``value`` is safe to use as a note id and file name.

    A ``TypeGuard`` so that callers narrowing on this get ``str`` rather than
    ``Any`` — the check and the type then cannot drift apart.
    """
    return isinstance(value, str) and bool(ID_PATTERN.match(value))


def _coerce_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def normalize_tag(value: Any) -> str | None:
    """Reduce a tag to its canonical form, or None if it is not usable.

    Tags are lower-cased and internally whitespace-collapsed so that "Work",
    "work" and "  work " are one tag rather than three. Commas are the
    separator in the editor, so they cannot appear inside a tag.
    """
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"\s+", " ", value.replace(",", " ")).strip().lower()
    return cleaned[:MAX_TAG_LENGTH] or None


def normalize_tags(values: Any) -> list[str]:
    """Canonicalise a list of tags, dropping blanks and duplicates.

    Order is preserved so the editor round-trips predictably. No cap is
    applied here: a file that already holds more tags than the editor would
    allow keeps them, because loading must never quietly discard data.
    """
    if isinstance(values, str):  # tolerate a single tag stored as a string
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []

    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        tag = normalize_tag(value)
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


@dataclass
class Note:
    """A single note, mirrored one-to-one with a JSON file on disk."""

    id: str = field(default_factory=new_id)
    title: str = ""
    content: str = ""
    color: str = DEFAULT_COLOR_NAME
    x: int | None = None
    y: int | None = None
    width: int = DEFAULT_NOTE_WIDTH
    height: int = DEFAULT_NOTE_HEIGHT
    minimized: bool = False
    order: int = 0
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        # Repairs here must never discard text. An id, a colour, or a window
        # size can be replaced with a sane default because none of them is
        # something the user wrote. Title and content are, so they are taken
        # exactly as found however long they are — truncating on load would
        # be written back as a real deletion by the next save.
        if not is_valid_id(self.id):
            self.id = new_id()
        if self.color not in COLORS:
            self.color = DEFAULT_COLOR_NAME
        self.width = max(MIN_NOTE_WIDTH, self.width)
        self.height = max(MIN_NOTE_HEIGHT, self.height)
        self.tags = normalize_tags(self.tags)

    # ─── Persistence helpers ──────────────────────────────────────

    @property
    def file_name(self) -> str:
        return f"{self.id}.json"

    @property
    def file_path(self) -> Path:
        """Absolute path of this note's file under the *current* notes dir.

        Resolved on each access rather than cached, so an override applied
        after the note was constructed is still honoured.
        """
        from notsucky.utils.paths import notes_dir

        return notes_dir() / self.file_name

    def touch(self) -> None:
        """Mark the note as modified now."""
        self.updated_at = utc_now()

    # ─── Serialization ────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> Note:
        """Build a note from untrusted data, repairing anything malformed.

        Unknown keys are dropped and bad values fall back to defaults, so a
        hand-edited or partially written file still loads instead of taking
        down the whole grid.
        """
        if not isinstance(data, dict):
            raise ValueError(f"Expected a JSON object, got {type(data).__name__}")

        raw_id = data.get("id")
        created = _coerce_str(data.get("created_at")) or utc_now()
        note = cls(
            id=raw_id if is_valid_id(raw_id) else new_id(),
            title=_coerce_str(data.get("title")),
            content=_coerce_str(data.get("content")),
            color=_coerce_str(data.get("color"), DEFAULT_COLOR_NAME),
            x=_coerce_optional_int(data.get("x")),
            y=_coerce_optional_int(data.get("y")),
            width=_coerce_optional_int(data.get("width")) or DEFAULT_NOTE_WIDTH,
            height=_coerce_optional_int(data.get("height")) or DEFAULT_NOTE_HEIGHT,
            minimized=bool(data.get("minimized", False)),
            order=_coerce_optional_int(data.get("order")) or 0,
            tags=normalize_tags(data.get("tags")),
            created_at=created,
            updated_at=_coerce_str(data.get("updated_at")) or created,
        )
        return note

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> Note:
        return cls.from_dict(json.loads(raw))


FIELD_NAMES = frozenset(f.name for f in fields(Note))
