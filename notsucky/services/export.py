"""Export notes to formats other tools can read.

Backups are for restoring this application; exports are for leaving it. The
distinction matters: a backup is a zip of internal JSON, while an export is
plain Markdown or text a person can open anywhere. Being easy to leave is
what makes a notes application safe to adopt.
"""

from __future__ import annotations

import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path

from notsucky.models.note import Note
from notsucky.services.file_manager import FileManager

logger = logging.getLogger(__name__)

FORMATS = ("md", "txt")

#: Characters no mainstream filesystem accepts in a name, plus control codes.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Names Windows reserves regardless of extension.
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_filename(note: Note, extension: str) -> str:
    """Build a readable, collision-resistant file name for a note.

    The note id is always appended: two notes may share a title, and a title
    may reduce to nothing once unsafe characters are stripped.
    """
    stem = _UNSAFE.sub(" ", note.title).strip()
    stem = re.sub(r"\s+", " ", stem).strip(" .")[:60].strip()
    if not stem or stem.upper() in _RESERVED:
        stem = "note"
    return f"{stem} [{note.id}].{extension}"


def render(note: Note, fmt: str = "md") -> str:
    """Render a single note as Markdown or plain text."""
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported format {fmt!r}; expected one of {FORMATS}")

    title = note.title or "Untitled"
    body = note.content.rstrip("\n")

    if fmt == "txt":
        underline = "=" * len(title)
        return f"{title}\n{underline}\n\n{body}\n"

    # Front matter keeps the metadata machine-readable without cluttering
    # the prose; it is the convention every Markdown notes tool understands.
    front = [
        "---",
        f"title: {title}",
        f"id: {note.id}",
        f"color: {note.color}",
        f"created: {note.created_at}",
        f"updated: {note.updated_at}",
        "---",
        "",
    ]
    return "\n".join(front) + f"# {title}\n\n{body}\n"


def export_note(note: Note, destination: Path, fmt: str = "md") -> Path:
    """Write one note into ``destination``. Returns the file written."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / safe_filename(note, fmt)
    path.write_text(render(note, fmt), encoding="utf-8")
    return path


def export_all(destination: Path, fmt: str = "md") -> list[Path]:
    """Export every note as an individual file. Returns the files written."""
    notes = FileManager.load_all()
    written = [export_note(note, destination, fmt) for note in notes]
    logger.info("Exported %d note(s) to %s", len(written), destination)
    return written


def export_archive(archive_path: Path, fmt: str = "md") -> Path | None:
    """Export every note into a single zip. Returns the archive, or None.

    Built under a temporary name and renamed into place, so an interrupted
    export never leaves a half-written archive looking complete.
    """
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported format {fmt!r}; expected one of {FORMATS}")

    notes = FileManager.load_all()
    if not notes:
        return None

    archive_path = Path(archive_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    partial = archive_path.with_suffix(archive_path.suffix + ".part")

    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
            for note in notes:
                archive.writestr(safe_filename(note, fmt), render(note, fmt))
        partial.replace(archive_path)
    except OSError:
        partial.unlink(missing_ok=True)
        raise

    logger.info("Exported %d note(s) into %s", len(notes), archive_path.name)
    return archive_path


def default_archive_name(fmt: str = "md") -> str:
    """A dated, unambiguous name for an export archive."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"notsucky-export-{fmt}-{stamp}.zip"
