"""Dated zip snapshots of the notes directory.

Notes are individually crash-safe (see :mod:`notsucky.services.file_manager`),
but nothing protects against the other kind of loss: a mistaken bulk delete, a
bad sync, a failing disk. A snapshot is a plain zip that any tool can open, so
recovery never depends on this application still running.
"""

from __future__ import annotations

import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from notsucky.services.file_manager import TRASH_DIR_NAME, FileManager
from notsucky.utils.paths import backup_dir

logger = logging.getLogger(__name__)

#: Snapshots kept before the oldest is pruned.
MAX_BACKUPS = 10

#: A new automatic snapshot is only taken once this much time has passed.
BACKUP_INTERVAL_SECONDS = 24 * 3600

BACKUP_PREFIX = "notes-"
BACKUP_SUFFIX = ".zip"


def list_backups() -> list[Path]:
    """Existing snapshots, newest first."""
    directory = backup_dir(create=False)
    if not directory.is_dir():
        return []
    try:
        found = list(directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"))
    except OSError as exc:  # pragma: no cover - unreadable backup directory
        logger.warning("Cannot list backups: %s", exc)
        return []
    return sorted(found, reverse=True)


def create_backup() -> Path | None:
    """Write a snapshot of every note. Returns its path, or None.

    None means there was nothing to back up. The zip is built under a
    temporary name and renamed into place, so a partial file is never mistaken
    for a usable snapshot. The trash is excluded — restoring a backup should
    not resurrect notes the user deleted.
    """
    notes = sorted(FileManager.directory().glob("*.json"))
    if not notes:
        return None

    directory = backup_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = directory / f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}"
    partial = target.with_suffix(".zip.part")

    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
            for note_file in notes:
                if TRASH_DIR_NAME in note_file.parts:
                    continue
                archive.write(note_file, arcname=note_file.name)
        partial.replace(target)
    except (OSError, zipfile.BadZipFile) as exc:
        logger.warning("Could not write a backup: %s", exc)
        partial.unlink(missing_ok=True)
        return None

    logger.info("Wrote backup %s (%d notes)", target.name, len(notes))
    prune_backups()
    return target


def prune_backups(keep: int = MAX_BACKUPS) -> int:
    """Delete all but the ``keep`` newest snapshots. Returns the count."""
    removed = 0
    for stale in list_backups()[keep:]:
        try:
            stale.unlink()
            removed += 1
        except OSError as exc:  # pragma: no cover - best effort
            logger.warning("Could not prune backup %s: %s", stale.name, exc)
    return removed


def seconds_since_last_backup() -> float | None:
    """Age of the newest snapshot in seconds, or None if there are none."""
    backups = list_backups()
    if not backups:
        return None
    try:
        return datetime.now(timezone.utc).timestamp() - backups[0].stat().st_mtime
    except OSError:  # pragma: no cover - vanished between listing and stat
        return None


def backup_if_due(interval_seconds: float = BACKUP_INTERVAL_SECONDS) -> Path | None:
    """Take a snapshot only if the newest one is older than ``interval``."""
    age = seconds_since_last_backup()
    if age is not None and age < interval_seconds:
        return None
    return create_backup()


def restore_backup(archive_path: Path, *, overwrite: bool = False) -> int:
    """Extract a snapshot back into the notes directory.

    Existing notes are left alone unless ``overwrite`` is set. Returns the
    number of notes written. Entries with a path separator are skipped, so a
    tampered archive cannot write outside the notes directory.
    """
    destination = FileManager.directory()
    written = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                candidate = Path(name)
                if candidate.name != name or candidate.suffix != ".json":
                    logger.warning("Skipping unsafe archive entry %r", name)
                    continue
                target = destination / candidate.name
                if target.exists() and not overwrite:
                    continue
                target.write_bytes(archive.read(name))
                written += 1
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise OSError(f"Could not restore {Path(archive_path).name}: {exc}") from exc

    logger.info("Restored %d note(s) from %s", written, Path(archive_path).name)
    return written
