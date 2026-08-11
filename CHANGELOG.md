# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.3.0] — 2026-08-10

Makes two guarantees explicit and enforces them with tests: **the application
never deletes a note you did not delete**, and **there is no sign-in**.

### Fixed — the app could delete your notes on its own

- **Removed the automatic trash sweep.** Every launch used to permanently
  delete trashed notes older than 30 days — unattended data loss, with no
  prompt and no way to intervene. Trashed notes are now kept indefinitely.
  `TRASH_RETENTION_DAYS` is `None`, `purge_trash()` with no argument removes
  nothing, and `run_maintenance` no longer calls it at all.
- **Removed content truncation on load.** `Note.__post_init__` capped content
  at 1,000,000 characters and titles at 200 *when reading a file*. The
  shortened value was then written back by the next save — including a save
  triggered by nothing more than moving the window — so a long note was
  silently and permanently cut down. Notes are now loaded and saved exactly as
  found, however long.
- **Removed truncation from the service layer.** `update_title` and
  `update_content` persist what they are given; only trailing blank lines that
  the editor itself adds are dropped.
- **Fixed the editor shrinking long notes on open.** `setPlainText` and
  `QLineEdit.setMaxLength` truncated an over-limit note the moment its window
  appeared. Each note now carries a growth ceiling of
  `max(limit, current length)`, so new typing is still bounded but nothing
  existing is ever cut.

Length limits still exist; they now bound how far *new* input can grow a note
rather than trimming what is already there. Memory is protected by refusing to
read an oversized *file* (8 MB) — which leaves the file untouched on disk —
rather than by discarding text after it has already been read.

### Changed

- The delete confirmation now says what actually happens: the file moves to
  the trash folder and stays there until you remove it.

### Added

- `tests/test_no_data_loss.py` — 31 tests covering both guarantees, including
  a walk of every module's AST that fails on any networking import, and one
  that makes `socket.socket` raise while exercising a full session.
- Verified end to end: 365 simulated launches over a store containing a
  1.5 M-character note, a decade-old trashed note, a corrupt file, and a
  stray non-note file. Nothing was deleted, nothing was shortened, and the
  old trashed note was still restorable.

## [1.2.0] — 2026-08-10

Follow-up review pass: security, performance, observability, and docs.

### Security

- **Unbounded reads.** A note file was read fully into memory before the
  1,000,000-character cap applied, so one 60 MB file was a 60 MB allocation
  during startup and a directory of them was an out-of-memory crash. Files
  over 8 MB are now skipped with a warning. Measured: a 60 MB file took
  `load_all` from 114 ms to 2 ms, by not reading it.
- **Zip bomb.** `restore_backup` wrote 200 MB to disk from a 199 KB archive.
  Declared sizes are now checked before any bytes are written — per entry,
  in total, and by entry count. The same archive now writes nothing.
- **Directory permissions.** The notes and backup directories are `chmod
  0700` on Linux and macOS; the default `0755` let any local account list
  note titles. Skipped on Windows, where the ACLs inherited from
  `%LOCALAPPDATA%` already restrict access and POSIX modes are cosmetic.
- Added [SECURITY.md](SECURITY.md) with the threat model, the controls, and
  the risks deliberately accepted.
- Tests now assert that no note title or body ever reaches the log.

### Performance

- **Card stylesheets moved to application scope.** Qt re-parses CSS for every
  widget carrying its own stylesheet; at five per card that was ~80% of the
  cost of building the grid. Cards now set a `noteColor` property against one
  shared sheet. Per-card construction: **350 µs → 142 µs**.
- **The grid streams.** Only the first 48 cards are built before the window
  paints; the rest arrive in chunks without blocking. At 2,000 notes, first
  paint went from **2,046 ms → 9 ms**, and total build from 2,046 ms → 365 ms.
  Dashboard startup: **1,603 ms → 93 ms**.
- Added `tests/test_performance.py` to guard against each of these
  regressing.

### Observability

- Qt's own warnings are routed into Python logging, so they land in the log
  file instead of a console a windowed app does not have.
- A crash handler logs uncaught exceptions with a full traceback and tells the
  user which file to look in.
- Startup steps are timed at INFO, so "it takes ages to open" localises itself.
- New `--diagnostics` prints versions, paths, and store counts for a bug
  report — and deliberately no note content, so it is safe to paste publicly.

### Documentation

- Added [OPERATIONS.md](OPERATIONS.md) (support and recovery runbook),
  [CONTRIBUTING.md](CONTRIBUTING.md), and [ROADMAP.md](ROADMAP.md).
- Added `tests/test_docs.py`, which fails when the docs reference a module,
  shortcut, CLI flag, or path that does not exist. It immediately caught three
  stale claims in the README.

### Code quality

- `mypy` now runs in CI and passes. Fixing its findings turned up real issues:
  `QApplication.instance()` can be a `QCoreApplication` with no stylesheet,
  `QLayout.takeAt` can return `None`, and `is_valid_id` is now a `TypeGuard`
  so the check and the type cannot drift apart.
- Extracted `views/qt_support.py` for Qt's Python/C++ lifetime split, and
  `clear_layout`, replacing four copies of the same `try/except RuntimeError`.
- CI additionally runs `pip-audit` and enforces a 90% coverage floor.

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

- Rewritten: **408 passing, 92% coverage** (was 8 failed, 7 errored, 11
  passed, with no GUI coverage), with a 90% floor enforced in CI.
- Tests no longer read or write the real notes directory.
- Added GUI coverage via `pytest-qt`, including named regression tests for the
  runaway drag, the undraggable window, the unpainted card background, the
  stranded dock, the sticky minimized flag, the duplicated window, and the
  resurrected deleted note.

## [1.0.0]

Initial refactor of the single-file "Sticky Notes v6" script into the
`notsucky` package. Never functional — see the blockers above.
