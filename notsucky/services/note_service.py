"""Business logic layer for note operations.

The view layer talks only to this module; it never writes files directly.
Every mutating call persists immediately and propagates
:class:`~notsucky.services.file_manager.StorageError` so the UI can tell the
user that their change did *not* reach the disk.
"""

from __future__ import annotations

import logging
from pathlib import Path

from notsucky.models.note import Note, new_id, utc_now
from notsucky.services import backup as backup_service
from notsucky.services.file_manager import FileManager
from notsucky.utils.constants import (
    COLORS,
    DEFAULT_COLOR_NAME,
    MIN_NOTE_HEIGHT,
    MIN_NOTE_WIDTH,
)

logger = logging.getLogger(__name__)


class NoteService:
    """Orchestrates note creation, updates, ordering, and deletion."""

    # ─── Creation ─────────────────────────────────────────────────

    @staticmethod
    def create(title: str = "", content: str = "", color: str = DEFAULT_COLOR_NAME) -> Note:
        """Create and persist a new note."""
        now = utc_now()
        note = Note(
            id=new_id(),
            title=title or f"Note {new_id()[:6]}",
            content=content,
            color=color if color in COLORS else DEFAULT_COLOR_NAME,
            created_at=now,
            updated_at=now,
        )
        FileManager.save_note(note)
        logger.info("Created note %s", note.id)
        return note

    # ─── Field updates ────────────────────────────────────────────

    @staticmethod
    def update_title(note: Note, new_title: str) -> bool:
        """Persist a new title verbatim. Returns False if nothing changed.

        Nothing is truncated here: the caller decides what the title is, and
        silently shortening it on the way to disk is a deletion the user did
        not ask for. Growth is bounded in the editor instead.
        """
        if new_title == note.title:
            return False
        note.title = new_title
        note.touch()
        FileManager.save_note(note)
        return True

    @staticmethod
    def update_content(note: Note, new_content: str) -> bool:
        """Persist new content. Returns False if nothing changed.

        Only trailing blank lines are dropped — the editor adds them and the
        user did not type them. Everything else is written exactly as given.
        """
        trimmed = new_content.rstrip("\n")
        if trimmed == note.content:
            return False
        note.content = trimmed
        note.touch()
        FileManager.save_note(note)
        return True

    @staticmethod
    def change_color(note: Note, color_name: str) -> bool:
        """Persist a new color. Returns False if unknown or unchanged."""
        if color_name not in COLORS or color_name == note.color:
            return False
        note.color = color_name
        note.touch()
        FileManager.save_note(note)
        return True

    @staticmethod
    def update_geometry(
        note: Note, x: int, y: int, width: int | None = None, height: int | None = None
    ) -> bool:
        """Persist a note window's position and size. False if unchanged.

        Geometry changes deliberately do *not* bump ``updated_at``: moving a
        window is not an edit, and treating it as one would reshuffle the
        dashboard every time a note is nudged.
        """
        new_width = max(MIN_NOTE_WIDTH, width if width is not None else note.width)
        new_height = max(MIN_NOTE_HEIGHT, height if height is not None else note.height)
        if (x, y, new_width, new_height) == (note.x, note.y, note.width, note.height):
            return False
        note.x, note.y = x, y
        note.width, note.height = new_width, new_height
        FileManager.save_note(note)
        return True

    # ─── State ────────────────────────────────────────────────────

    @staticmethod
    def set_minimized(note: Note, minimized: bool) -> bool:
        """Persist the minimized flag. Returns False if unchanged."""
        if note.minimized == minimized:
            return False
        note.minimized = minimized
        note.touch()
        FileManager.save_note(note)
        return True

    @classmethod
    def toggle_minimize(cls, note: Note) -> bool:
        """Flip the minimized flag and return its new value."""
        cls.set_minimized(note, not note.minimized)
        return note.minimized

    # ─── Ordering ─────────────────────────────────────────────────

    @staticmethod
    def reorder(notes: list[Note], source_id: str, target_id: str) -> bool:
        """Move ``source_id`` to ``target_id``'s slot within ``notes``.

        ``notes`` must be in current display order. Every note is renumbered
        from 1 so that positions stay dense and unambiguous; notes whose stored
        order is already correct are not rewritten.
        """
        if source_id == target_id:
            return False
        index = {n.id: i for i, n in enumerate(notes)}
        if source_id not in index or target_id not in index:
            return False

        reordered = list(notes)
        moved = reordered.pop(index[source_id])
        reordered.insert(index[target_id], moved)

        changed = False
        for position, note in enumerate(reordered, start=1):
            if note.order != position:
                note.order = position
                FileManager.save_note(note)
                changed = True
        return changed

    # ─── Deletion ─────────────────────────────────────────────────

    @staticmethod
    def delete(note: Note) -> Path | None:
        """Move a note to the trash. Returns the token needed to undo it.

        None means there was no file to delete.
        """
        trashed = FileManager.delete_note(note)
        logger.info("Deleted note %s (trashed=%s)", note.id, trashed is not None)
        return trashed

    @staticmethod
    def undo_delete(trash_path: Path) -> Note | None:
        """Restore a note previously returned by :meth:`delete`."""
        return FileManager.restore_from_trash(trash_path)

    # ─── Housekeeping ─────────────────────────────────────────────

    @staticmethod
    def run_maintenance(*, backup: bool = True) -> None:
        """Startup housekeeping. Deliberately additive only.

        This used to sweep the trash of anything older than 30 days, which
        made the application delete a user's notes on its own, unattended,
        with no way to intervene. Nothing here removes note data any more:
        trashed notes stay until the user removes them. The only step left
        is taking a backup, and it is best-effort — nobody should be unable
        to open their notes because a snapshot failed.
        """
        if backup:
            try:
                backup_service.backup_if_due()
            except Exception:
                logger.exception("Backup failed")
