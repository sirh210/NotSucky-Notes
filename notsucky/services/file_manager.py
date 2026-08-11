"""File-based persistence for notes.

Every write goes through :meth:`FileManager.save_note`, which writes to a
temporary file in the same directory and then atomically replaces the target.
A crash or full disk therefore leaves the previous version of the note intact
rather than a half-written file.

Deletion is likewise non-destructive: notes are moved into a ``.trash``
subdirectory and only removed for good once they are older than
:data:`TRASH_RETENTION_DAYS`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from notsucky.models.note import Note, is_valid_id, normalize_tag
from notsucky.utils.paths import notes_dir

logger = logging.getLogger(__name__)

#: Subdirectory of the notes directory holding deleted notes. The leading dot
#: keeps it out of ``*.json`` globs and out of the user's way.
TRASH_DIR_NAME = ".trash"

#: Trashed notes are kept indefinitely. Nothing in the application removes
#: them on a timer: :meth:`FileManager.purge_trash` exists for a user who
#: explicitly asks to reclaim the space, and is never called automatically.
TRASH_RETENTION_DAYS: int | None = None

#: Largest note file that will be read into memory. A note is capped at
#: 1,000,000 characters, which is at most ~4 MB of UTF-8 plus JSON overhead,
#: so anything past this is corrupt or hostile. Without the guard a single
#: oversized file — or a directory of them — is an out-of-memory crash on
#: startup, since the whole file is read before the content cap applies.
MAX_NOTE_FILE_BYTES = 8 * 1024 * 1024


class StorageError(RuntimeError):
    """Raised when a note could not be read from or written to disk."""


class FileManager:
    """Handles all file I/O for note persistence."""

    # ─── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def directory() -> Path:
        """Return (creating if needed) the directory holding note files."""
        return notes_dir()

    @classmethod
    def ensure_dir(cls) -> Path:
        return cls.directory()

    @classmethod
    def read_note_file(cls, path: Path) -> Note:
        """Read and parse one note file, refusing implausibly large ones.

        Raises:
            ValueError: if the file exceeds :data:`MAX_NOTE_FILE_BYTES`.
            OSError, json.JSONDecodeError, UnicodeDecodeError: as usual.
        """
        size = path.stat().st_size
        if size > MAX_NOTE_FILE_BYTES:
            raise ValueError(
                f"{path.name} is {size} bytes, over the {MAX_NOTE_FILE_BYTES} byte limit"
            )
        return Note.from_json(path.read_text(encoding="utf-8"))

    @classmethod
    def path_for(cls, note_id: str) -> Path:
        """Return the file path for ``note_id``.

        Raises:
            ValueError: if the id could escape the notes directory.
        """
        if not is_valid_id(note_id):
            raise ValueError(f"Unsafe note id: {note_id!r}")
        return cls.directory() / f"{note_id}.json"

    # ─── CRUD operations ──────────────────────────────────────────

    @classmethod
    def save_note(cls, note: Note) -> Path:
        """Atomically persist a single note. Returns the file path.

        Raises:
            StorageError: if the note could not be written.
        """
        path = cls.path_for(note.id)
        payload = json.dumps(note.to_dict(), indent=2, ensure_ascii=False)

        tmp_path: str | None = None
        try:
            # Same directory as the target, so os.replace stays atomic
            # (a cross-filesystem replace is not).
            handle, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), prefix=f".{note.id}.", suffix=".tmp"
            )
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
            tmp_path = None
        except (OSError, ValueError) as exc:
            logger.error("Failed to save note %s: %s", note.id, exc)
            raise StorageError(f"Could not save note {note.id}: {exc}") from exc
        finally:
            if tmp_path is not None:
                with contextlib.suppress(OSError):  # best-effort cleanup
                    os.unlink(tmp_path)

        return path

    @classmethod
    def save_all(cls, notes: list[Note]) -> list[Note]:
        """Save many notes, returning the ones that failed."""
        failed: list[Note] = []
        for note in notes:
            try:
                cls.save_note(note)
            except StorageError:
                failed.append(note)
        return failed

    @classmethod
    def delete_note(cls, note: Note) -> Path | None:
        """Move a note into the trash. Returns its trash path, or None.

        None means there was nothing to delete. The returned path is the token
        :meth:`restore_from_trash` needs, which is what makes undo possible.

        Raises:
            StorageError: if the file exists but could not be moved.
        """
        try:
            path = cls.path_for(note.id)
        except ValueError:
            return None  # unsafe id: there is no addressable file
        if not path.exists():
            return None

        destination = cls.trash_directory() / trash_name(note.id)
        try:
            os.replace(path, destination)
        except OSError as exc:
            logger.error("Failed to move note %s to the trash: %s", note.id, exc)
            raise StorageError(f"Could not delete note {note.id}: {exc}") from exc
        logger.info("Moved note %s to the trash", note.id)
        return destination

    @classmethod
    def purge_note(cls, note: Note) -> bool:
        """Delete a note's file outright, bypassing the trash."""
        try:
            path = cls.path_for(note.id)
        except ValueError:
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            logger.error("Failed to delete note %s: %s", note.id, exc)
            raise StorageError(f"Could not delete note {note.id}: {exc}") from exc
        return True

    # ─── Trash ────────────────────────────────────────────────────

    @classmethod
    def trash_directory(cls) -> Path:
        """Return (creating if needed) the trash subdirectory."""
        path = cls.directory() / TRASH_DIR_NAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def list_trash(cls) -> list[Path]:
        """Trash entries, most recently deleted first."""
        try:
            entries = list(cls.trash_directory().glob("*.json"))
        except OSError as exc:
            logger.error("Cannot list the trash: %s", exc)
            return []
        return sorted(entries, key=lambda p: (trash_timestamp(p) or 0.0), reverse=True)

    @classmethod
    def restore_from_trash(cls, trash_path: Path) -> Note | None:
        """Move a trashed note back into the notes directory.

        Returns the restored note, or None if the entry is gone or unreadable.
        A note whose id has been taken by a new note since deletion is restored
        under a fresh id rather than overwriting the newer one.
        """
        trash_path = Path(trash_path)
        if not trash_path.is_file():
            return None
        if trash_path.parent.resolve() != cls.trash_directory().resolve():
            logger.warning("Refusing to restore from outside the trash: %s", trash_path)
            return None

        try:
            note = cls.read_note_file(trash_path)
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError, OSError) as exc:
            logger.error("Cannot restore unreadable trash entry %s: %s", trash_path.name, exc)
            return None

        if cls.path_for(note.id).exists():
            note.id = _fresh_id_avoiding(cls)
            logger.info("Restoring under a new id %s; the original was taken", note.id)

        try:
            cls.save_note(note)
            trash_path.unlink(missing_ok=True)
        except StorageError:
            raise
        except OSError as exc:
            logger.error("Failed to clear trash entry %s: %s", trash_path.name, exc)
        logger.info("Restored note %s from the trash", note.id)
        return note

    @classmethod
    def purge_trash(cls, max_age_days: int | None = TRASH_RETENTION_DAYS) -> int:
        """Permanently remove trash entries older than ``max_age_days``.

        **Only ever called when a user explicitly asks to reclaim space.**
        Nothing in the application calls it on a timer or at startup, and
        ``max_age_days=None`` — the default — removes nothing at all, so an
        accidental call cannot destroy anything.

        Returns the number of entries removed. Entries with an unparseable
        name are kept rather than guessed at.
        """
        if max_age_days is None:
            return 0
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86_400
        removed = 0
        for entry in cls.list_trash():
            stamp = trash_timestamp(entry)
            if stamp is None or stamp >= cutoff:
                continue
            try:
                entry.unlink()
                removed += 1
            except OSError as exc:  # pragma: no cover - best effort
                logger.warning("Could not purge trash entry %s: %s", entry.name, exc)
        if removed:
            logger.info("Purged %d expired trash entr%s", removed, "y" if removed == 1 else "ies")
        return removed

    @classmethod
    def empty_trash(cls) -> int:
        """Permanently remove every trash entry. Returns the count."""
        return cls.purge_trash(max_age_days=-1)

    @classmethod
    def load_all(cls) -> list[Note]:
        """Load every readable note from disk, in display order.

        Unreadable or corrupt files are logged and skipped rather than
        aborting the whole load.
        """
        directory = cls.directory()
        notes: list[Note] = []
        try:
            candidates = sorted(directory.glob("*.json"))
        except OSError as exc:
            logger.error("Cannot list notes directory %s: %s", directory, exc)
            return []

        for json_file in candidates:
            try:
                notes.append(cls.read_note_file(json_file))
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError, OSError) as exc:
                logger.warning("Skipping unreadable note file %s: %s", json_file.name, exc)
        return sort_for_display(notes)

    @classmethod
    def load_by_id(cls, note_id: str) -> Note | None:
        """Load a single note by id, or None if missing or unreadable."""
        try:
            path = cls.path_for(note_id)
        except ValueError:
            logger.warning("Refusing to load note with unsafe id %r", note_id)
            return None
        try:
            return cls.read_note_file(path)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError, OSError) as exc:
            logger.error("Failed to load note %s: %s", note_id, exc)
            return None

    @classmethod
    def search(cls, query: str) -> list[Note]:
        """Return notes whose title or content contains ``query``."""
        return filter_notes(cls.load_all(), query)


def trash_name(note_id: str, when: float | None = None) -> str:
    """Build a trash file name of the form ``<id>.<unix-seconds>.json``.

    The deletion time lives in the name rather than relying on the file's
    mtime, which archivers, syncing tools, and copies do not preserve.
    """
    stamp = datetime.now(timezone.utc).timestamp() if when is None else when
    return f"{note_id}.{int(stamp)}.json"


def trash_timestamp(path: Path) -> float | None:
    """Recover the deletion time from a trash file name, or None."""
    parts = path.name.rsplit(".", 2)
    if len(parts) != 3 or parts[2] != "json":
        return None
    try:
        return float(parts[1])
    except ValueError:
        return None


def trash_note_id(path: Path) -> str | None:
    """Recover the original note id from a trash file name, or None."""
    parts = path.name.rsplit(".", 2)
    if len(parts) != 3 or not is_valid_id(parts[0]):
        return None
    return parts[0]


def _fresh_id_avoiding(manager: type[FileManager]) -> str:
    """Generate a note id that is not already present on disk."""
    from notsucky.models.note import new_id

    for _ in range(100):
        candidate = new_id()
        if not (manager.directory() / f"{candidate}.json").exists():
            return candidate
    return new_id()  # pragma: no cover - 100 collisions is not a real scenario


def filter_notes(
    notes: list[Note], query: str, required_tags: Iterable[str] | None = None
) -> list[Note]:
    """Filter by text and by tags.

    Text is a case-insensitive substring of the title, the content, or any
    tag. Tags are combined with AND — selecting two narrows the result rather
    than widening it, which is what makes a tag filter useful for finding one
    note instead of a category.

    Kept as a free function so the dashboard can filter an already-loaded list
    instead of re-reading every file on each keystroke.
    """
    wanted = {t for t in (normalize_tag(t) for t in (required_tags or ())) if t}
    needle = query.strip().lower()

    result = notes if not wanted else [n for n in notes if wanted <= set(n.tags)]
    if not needle:
        return list(result)
    return [
        n
        for n in result
        if needle in n.title.lower()
        or needle in n.content.lower()
        or any(needle in tag for tag in n.tags)
    ]


def all_tags(notes: Iterable[Note]) -> list[str]:
    """Every tag in use, most-used first, then alphabetically.

    Frequency ordering puts the tags worth clicking at the front, which
    matters once there are more than a screenful.
    """
    counts: dict[str, int] = {}
    for note in notes:
        for tag in note.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts, key=lambda tag: (-counts[tag], tag))


def tag_counts(notes: Iterable[Note]) -> dict[str, int]:
    """How many notes carry each tag."""
    counts: dict[str, int] = {}
    for note in notes:
        for tag in note.tags:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def sort_for_display(notes: list[Note]) -> list[Note]:
    """Sort by the user's manual ordering, then most-recently-updated first.

    ``order`` defaults to 0 for notes that have never been dragged, so those
    fall back to recency while explicitly ordered notes keep their position.
    """
    # Two stable passes: the recency pass survives as the tie-break within
    # each ``order`` group, which a single composite key cannot express for
    # descending strings.
    by_recency = sorted(notes, key=lambda n: n.updated_at or "", reverse=True)
    return sorted(by_recency, key=lambda n: n.order)
