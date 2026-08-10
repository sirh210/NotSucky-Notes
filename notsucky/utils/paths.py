"""Resolution of on-disk locations used by the application.

Storage location is resolved once, lazily, in this priority order:

1. An explicit override set via :func:`set_notes_dir` (used by tests and by the
   ``--notes-dir`` command line flag).
2. The ``NOTSUCKY_NOTES_DIR`` environment variable.
3. A per-user data directory appropriate to the platform.

Everything else in the codebase must go through :func:`notes_dir` rather than
capturing a module-level constant, so that overrides always take effect.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "NotSucky Notes"
APP_SLUG = "notsucky-notes"

ENV_NOTES_DIR = "NOTSUCKY_NOTES_DIR"

#: Written into the notes directory once legacy data has been imported, so the
#: import is never attempted a second time (even if the user empties the dir).
MIGRATION_MARKER = ".migrated-from-legacy"

_override: Path | None = None
_resolved: Path | None = None


# ─── Platform data directories ────────────────────────────────────


def user_data_dir() -> Path:
    """Return the per-user data directory for this application."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / APP_SLUG


def log_dir() -> Path:
    """Return the directory used for rotating application logs."""
    return user_data_dir() / "logs"


def backup_dir(*, create: bool = True) -> Path:
    """Return the directory holding note backups.

    Backups sit beside the notes rather than inside them, so a snapshot never
    ends up inside the next snapshot and the notes directory stays a flat set
    of note files.
    """
    target = notes_dir(create=False).parent / "backups"
    if create:
        target.mkdir(parents=True, exist_ok=True)
        restrict_permissions(target)
    return target


# ─── Notes directory ──────────────────────────────────────────────


def set_notes_dir(path: Path | str | None) -> None:
    """Override the notes directory, or pass ``None`` to clear the override.

    Clears the resolution cache so the next :func:`notes_dir` call re-resolves.
    """
    global _override, _resolved
    _override = Path(path).expanduser() if path is not None else None
    _resolved = None


def _resolve_notes_dir() -> Path:
    if _override is not None:
        return _override
    env_value = os.environ.get(ENV_NOTES_DIR)
    if env_value:
        return Path(env_value).expanduser()
    return user_data_dir() / "notes"


def notes_dir(*, create: bool = True) -> Path:
    """Return the directory holding note JSON files.

    The result is cached until :func:`set_notes_dir` is called. When ``create``
    is true the directory is created and any legacy note store is imported.
    """
    global _resolved
    if _resolved is not None and create:
        return _resolved

    target = _resolve_notes_dir()
    if not create:
        return target

    target.mkdir(parents=True, exist_ok=True)
    restrict_permissions(target)
    _migrate_legacy_notes(target)
    _resolved = target
    return target


def restrict_permissions(path: Path) -> None:
    """Make a directory owner-only on POSIX. No-op elsewhere.

    Notes are private by nature, and the default 0755 lets any local account
    list note titles. Windows inherits ACLs from the user's AppData, which is
    already owner-only, and chmod there is largely cosmetic — so this is
    skipped rather than faked.
    """
    if sys.platform == "win32":
        return
    try:
        path.chmod(0o700)
    except OSError as exc:  # pragma: no cover - unusual filesystems
        logger.debug("Could not restrict permissions on %s: %s", path, exc)


# ─── Legacy data import ───────────────────────────────────────────


def _legacy_candidates() -> list[Path]:
    """Directories used by earlier versions, newest layout first.

    ``parents[2]`` is the project root when running from a source checkout; for
    an installed package it points inside ``site-packages`` and simply will not
    exist, so both candidates are guarded by an existence check.
    """
    package_root = Path(__file__).resolve().parents[1]
    return [
        package_root.parent / "notes",  # project-root ./notes (v1 source layout)
        package_root / "notes",         # notsucky/notes (v1 constants bug)
    ]


def _migrate_legacy_notes(target: Path) -> None:
    """Copy notes from a pre-1.1 location into ``target``, once.

    Files are *copied*, never moved: the originals remain as a backup and the
    operation is safe to interrupt. Existing files in ``target`` always win.
    """
    marker = target / MIGRATION_MARKER
    if marker.exists():
        return

    imported = 0
    for legacy in _legacy_candidates():
        if not legacy.is_dir() or legacy.resolve() == target.resolve():
            continue
        for source in sorted(legacy.glob("*.json")):
            destination = target / source.name
            if destination.exists():
                continue
            try:
                shutil.copy2(source, destination)
                imported += 1
            except OSError as exc:
                logger.warning("Could not import legacy note %s: %s", source, exc)

    if imported:
        logger.info("Imported %d note(s) from a previous version into %s", imported, target)

    try:
        marker.write_text(
            "Legacy note import already performed. Delete this file to run it again.\n",
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - non-fatal, just retries next launch
        logger.warning("Could not write migration marker in %s: %s", target, exc)
