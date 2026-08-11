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
