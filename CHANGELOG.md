# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.0] — 2026-08-10

A production-readiness pass. Version 1.0.0 could not start; see
[AUDIT.md](AUDIT.md) for the full findings.

### Fixed — blockers

- **The application now starts.** `card_widget.py` imported `QMouseEvent` from
  `PySide6.QtCore` instead of `QtGui`, raising `ImportError` on any dashboard
  refresh, and used `QSizePolicy` without importing it.
- **The package now builds.** `build-backend` pointed at a nonexistent module
  (`setuptools.backends._legacy:_Backend`).
- **The package now installs completely.** `models/`, `services/`, `utils/`,
  and `views/` had no `__init__.py` and were omitted from the distribution.

### Fixed — data integrity

- Notes were written to `notsucky/notes` inside the package rather than a user
  directory — invisible to the user, and inside `site-packages` when
  installed. Storage now resolves to a per-platform user data directory, with
  a one-time copy migration from the old locations.
- Saves were not atomic; an interrupted write destroyed the note. Writes now
  go to a temporary file and `os.replace` into position.
- Save failures were logged and swallowed. They now surface in the note's
  status bar and the dashboard status bar.
- Note ids became file names with no validation, allowing a hand-edited file
  to write outside the notes directory.
- Loading a malformed note file could break the whole grid; fields are now
  coerced or defaulted individually.

### Fixed — behaviour

- **Runaway window drag.** The drag delta compounded on every mouse-move
  event. One saved note had reached `x = -45088`.
- **Notes could not be dragged at all** — an inverted `childAt` guard rejected
  exactly the presses that should have started a drag.
- **Notes could not be resized**, despite being advertised as resizable.
- **Cards rendered with no background colour**, leaving pale text on a dark
  panel (`WA_StyledBackground` is required on `QWidget` subclasses).
- Off-screen saved positions were restored blindly, putting notes out of
  reach.
- Auto-save fired once per keystroke instead of once per typing burst.
- The minimized dock was never restored at startup, stranding minimized notes.
- Restoring a note never cleared its `minimized` flag on disk.
- Reopening a minimized note created a second, orphaned window.
- Deleting an open note left its window alive; the next auto-save rewrote the
  deleted file.
- Closing the dashboard left note windows open, keeping the process alive and
  discarding unsaved edits.
- `delete_note` always reported success, even when no file existed.
- Note placement used `hash()`, which is salted per process, so unpositioned
  notes moved on every launch.
- CSS typo `border-top-right-right-radius` left a corner unrounded.

### Added

- **Undoable delete.** Notes move to a `.trash` subdirectory instead of being
  unlinked; `Ctrl+Z` restores the last one, and entries survive 30 days before
  a startup sweep purges them. Restoring a note whose id has since been reused
  gives it a fresh id rather than overwriting the newer note.
- **Automatic backups.** A dated zip snapshot of every note, taken at most
  once a day at startup, keeping the ten most recent. Plus
  `--backup-now`, `--list-backups`, and `--no-backup`, which run without a
  QApplication so they work over SSH and from cron.
- **An application icon**, drawn at runtime at seven sizes so there is no
  binary asset in the repository and no scaling blur.
- **Continuous integration** — `ruff` and the full suite on Linux and Windows
  across Python 3.10–3.13, plus a job that builds the wheel and verifies every
  subpackage imports from a clean install.
- **Drag-to-reorder**, which the README had advertised but which did not
  exist. Cards are drag sources and drop targets; the order is persisted.
- Resize grips and persisted window size (`width`/`height` on the note).
- An explicit `⠿` drag handle on each note.
- Keyboard shortcuts: `Ctrl+N`, `Ctrl+F`, `Ctrl+Z`, `Ctrl+W`, `Ctrl+M`,
  `Ctrl+S`, `F5`, `Esc`.
- CLI: `--notes-dir`, `--log-level`, `--no-log-file`, `--version`; a
  `notsucky-notes-cli` console alias, and `python -m notsucky`.
- Rotating file logging in the user data directory.
- `NOTSUCKY_NOTES_DIR` environment variable.
- Responsive grid column count (1–6, from the window width).
- Accessible names, tooltips, and a status bar for transient messages.
- `LICENSE`, `.gitignore`, `CHANGELOG.md`, `AUDIT.md`, `requirements-dev.txt`.

### Changed

- Timestamps are timezone-aware UTC. Naive 1.0 timestamps still load.
- Title and content are capped at 200 and 1,000,000 characters.
- Foreground colours darkened to meet WCAG AA contrast (was ≈2.3:1).
- Search filters an in-memory list instead of re-reading every file on each
  keystroke, and is debounced.
- Storage location is resolved through a function rather than a module-level
  constant, so overrides always take effect.
- `ruff` now enforces `E,F,W,I,UP,B,C4,SIM,RUF` (was 104 errors, now clean).

### Changed — breaking

- `FileManager.delete_note` and `NoteService.delete` return the trash path
  (`Path | None`) instead of a bool, since undo needs that token.
  `FileManager.purge_note` is the permanent delete.

### Removed

- The superseded 22 KB `main.py` monolith, `_dump.py`, and `_dump.py.tmp`.
  They were staged in `archive/` for the initial commit so that git holds a
  copy, then removed in the commit that followed.

### Tests

- Rewritten: **304 passing, 94% coverage** (was 8 failed, 7 errored, 11
  passed, with no GUI coverage).
- Tests no longer read or write the real notes directory.
- Added GUI coverage via `pytest-qt`, including named regression tests for the
  runaway drag, the undraggable window, the unpainted card background, the
  stranded dock, the sticky minimized flag, the duplicated window, and the
  resurrected deleted note.

## [1.0.0]

Initial refactor of the single-file "Sticky Notes v6" script into the
`notsucky` package. Never functional — see the blockers above.
