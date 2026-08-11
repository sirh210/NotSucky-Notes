"""Shared pytest fixtures.

The critical guarantee here is isolation: an autouse fixture repoints the
notes directory at a per-test temporary path, so no test can read or destroy
the user's real notes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the project importable when pytest is run from a source checkout
# without the package installed.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from notsucky.utils import paths  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_notes_dir(tmp_path, monkeypatch):
    """Point every test at its own empty notes directory."""
    target = tmp_path / "notes"
    target.mkdir()
    # Suppress the legacy import so a developer's ./notes never leaks in.
    (target / paths.MIGRATION_MARKER).write_text("test", encoding="utf-8")
    monkeypatch.delenv(paths.ENV_NOTES_DIR, raising=False)

    paths.set_notes_dir(target)
    # Settings live beside the notes, so the cached copy has to go too or one
    # test's theme choice leaks into the next.
    from notsucky.utils import settings

    settings.reset_cache()
    try:
        yield target
    finally:
        paths.set_notes_dir(None)
        settings.reset_cache()


@pytest.fixture()
def notes_dir(isolated_notes_dir) -> Path:
    """Explicit alias for tests that want to inspect files directly."""
    return isolated_notes_dir


@pytest.fixture()
def make_note():
    """Factory creating and persisting a note with sensible defaults."""
    from notsucky.services.note_service import NoteService

    def _make(title: str = "Test", content: str = "", color: str = "Yellow"):
        return NoteService.create(title=title, content=content, color=color)

    return _make
