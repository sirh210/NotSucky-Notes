# 📝 NotSucky Notes

A sticky notes application built with Python and PySide6 (Qt). Floating,
resizable note windows over a searchable, drag-to-reorder dashboard, with
plain JSON files on disk and no database.

## Features

- **Floating note windows** — drag by the `⠿` handle or the title bar, resize
  from the grip in the bottom-right corner. Position and size are remembered.
- **Drag-to-reorder grid** — drag one card onto another to move it there; the
  arrangement is persisted.
- **Responsive dashboard** — the column count follows the window width.
- **Six colour themes** — pick one from the swatches in a note's title bar.
- **Instant filter** — search titles and content as you type.
- **Debounced auto-save** — a burst of typing produces one write, not one per
  keystroke; edits are also flushed on close, minimize, and quit.
- **Crash-safe writes** — notes are written atomically, so an interrupted save
  leaves the previous version intact rather than a truncated file.
- **Nothing is ever deleted behind your back** — see the guarantee below.
- **Undoable delete** — deleting moves the note's file into a trash folder,
  where it stays until *you* remove it. `Ctrl+Z` puts the last one back.
- **Automatic backups** — a dated zip snapshot of every note, taken at most
  once a day, with the ten most recent kept.
- **Works entirely offline** — no account, no sign-in, no network code.
- **Minimize to dock** — park notes in the strip at the bottom; the dock is
  restored when you reopen the app.
- **Local file storage** — one human-readable JSON file per note.

## Installation

```bash
git clone https://github.com/sirh210/NotSucky-Notes.git
cd NotSucky-Notes

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -e .                # or: pip install -r requirements.txt
```

Requires Python 3.10+.

## Two guarantees

**Your notes are never deleted except by you.** Nothing runs on a timer to
tidy them up. Deleting moves the note's file into `notes/.trash/`, where it
stays indefinitely — there is no expiry sweep. Files the app cannot read
(corrupt, oversized, written by something else) are skipped and left exactly
where they are, never cleaned up. No length limit ever shortens a note that
already exists: limits bound how far new typing can grow a note, and a note
that is already longer keeps its current length as its ceiling. Every write is
atomic, so an interrupted save leaves the previous version intact.

The one way to permanently remove a note is to delete the file yourself, from
`notes/.trash/`, in your file manager.

**There is no sign-in, and there cannot be.** The package imports no
networking library of any kind — no `socket`, no `urllib`, no `requests`, and
only Qt's `QtCore`, `QtGui`, and `QtWidgets`. There is no account, no
telemetry, and nothing to log in to. Both guarantees are enforced by tests in
`tests/test_no_data_loss.py`, including one that makes opening a socket raise.

## Usage

```bash
notsucky-notes                  # installed GUI launcher
python -m notsucky              # equivalent, from a checkout

notsucky-notes-cli --help       # console alias (--help is readable on Windows)
notsucky-notes --notes-dir ~/my-notes
notsucky-notes --log-level DEBUG
```

### Backups from the command line

These run without starting the GUI, so they work over SSH and from cron or
Task Scheduler:

```bash
notsucky-notes-cli --backup-now      # write a snapshot and exit
notsucky-notes-cli --list-backups    # show what snapshots exist
notsucky-notes --no-backup           # start without the daily snapshot
```

### Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+N` | New note |
| `Ctrl+F` | Focus the filter |
| `Esc` | Clear the filter |
| `Ctrl+Z` | Undo the last delete |
| `F5` | Reload from disk |
| `Ctrl+W` | Close the focused note |
| `Ctrl+M` | Minimize the focused note to the dock |
| `Ctrl+S` | Force-save the focused note |

## Where your notes are stored

By default, notes live in a per-user data directory:

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\NotSucky Notes\notes` |
| macOS | `~/Library/Application Support/NotSucky Notes/notes` |
| Linux | `$XDG_DATA_HOME/notsucky-notes/notes` (or `~/.local/share/...`) |

The dashboard header always shows the active path. Override it with either:

```bash
export NOTSUCKY_NOTES_DIR=/path/to/notes    # environment variable
notsucky-notes --notes-dir /path/to/notes   # command line flag (wins)
```

Alongside the notes you will find:

| Path | Contents |
| --- | --- |
| `notes/` | One JSON file per note |
| `notes/.trash/` | Deleted notes, kept indefinitely |
| `backups/` | Dated zip snapshots, ten kept |
| `logs/notsucky.log` | Rotating log, 3 × 1 MB (`--no-log-file` to disable) |

**Recovering a note.** `Ctrl+Z` undoes the most recent delete. Beyond that,
copy the file out of `notes/.trash/` — the name is `<id>.<unix-time>.json` —
and drop it into `notes/` with the timestamp removed. To roll back further,
unzip a snapshot from `backups/` over `notes/`.

**Reclaiming space.** The trash grows forever by design. Delete files from
`notes/.trash/` yourself whenever you want the space back; the application
will never do it for you.

> **Upgrading from 1.0?** Versions before 1.1 stored notes inside the project
> directory. On first launch your existing notes are **copied** into the new
> location automatically. The originals are left untouched as a backup, and
> the import runs only once.

## Project structure

```
NotSucky-Notes/
├── notsucky/
│   ├── __main__.py           # python -m notsucky
│   ├── main.py               # entry point & CLI
│   ├── models/note.py        # Note dataclass, validation, (de)serialization
│   ├── services/
│   │   ├── file_manager.py   # atomic file I/O, trash, loading, sorting
│   │   ├── note_service.py   # business logic; the only writer the views use
│   │   └── backup.py         # zip snapshots, retention, restore
│   ├── views/
│   │   ├── dashboard.py      # main window, grid, dock, lifecycle
│   │   ├── card_widget.py    # grid card; drag source and drop target
│   │   ├── note_widget.py    # floating note window
│   │   ├── qt_support.py     # Qt object-lifetime helpers
│   │   └── icon.py           # application icon, drawn at runtime
│   └── utils/
│       ├── constants.py      # colors, limits, timings
│       ├── paths.py          # storage location resolution & migration
│       ├── geometry.py       # pure screen-clamping and layout maths
│       ├── diagnostics.py    # timings, crash handler, support report
│       └── logging_config.py
├── tests/                    # 408 tests, 92% coverage
├── .github/workflows/ci.yml  # lint, types, audit, test matrix, wheel check
├── AUDIT.md                  # production-readiness audit
├── SECURITY.md               # threat model and controls
├── OPERATIONS.md             # support and recovery runbook
├── CONTRIBUTING.md
├── ROADMAP.md
└── CHANGELOG.md
```

## Architecture

- **Models** — plain data with validation and serialization; no I/O, no Qt.
- **Services** — persistence and business logic; no Qt imports at all.
- **Views** — Qt widgets that call services and never touch the filesystem.
- **Utils** — constants plus pure helpers, unit-testable without a display.

Two rules keep this honest and are worth preserving:

1. **Storage location is resolved through a function, never captured as a
   module constant.** A module-level `NOTES_DIR` gets frozen at import by
   every module that imports it, which is what made the location impossible to
   override in 1.0.
2. **Writes are atomic and their failures propagate.** `StorageError` reaches
   the UI; nothing swallows a failed save.

## Development

```bash
pip install -r requirements-dev.txt

pytest                                        # the full suite
pytest --cov=notsucky --cov-report=term-missing
ruff check .
python -m build --wheel
```

GUI tests need a Qt platform plugin. On a headless machine:

```bash
QT_QPA_PLATFORM=offscreen pytest
```

Tests never touch your real notes: an autouse fixture repoints storage at a
temporary directory for every test.

CI runs `ruff`, `mypy`, and `pip-audit`, then the full suite on Linux and
Windows across Python 3.10–3.13, then builds the wheel and verifies that every
subpackage imports from a clean install. Coverage below 90% fails the build.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the layering rules and the reasons
behind them.

## Troubleshooting

```bash
notsucky-notes-cli --diagnostics    # versions, paths, and store counts
notsucky-notes --log-level DEBUG    # verbose logging
```

The diagnostics output contains no note titles or contents, so it is safe to
paste into an issue. [OPERATIONS.md](OPERATIONS.md) covers recovering deleted
notes, restoring backups, and reading the logs.

## Documentation

| Document | What it covers |
| --- | --- |
| [AUDIT.md](AUDIT.md) | The production-readiness audit and every finding |
| [docs/audit-report.html](docs/audit-report.html) | The same audit as a self-contained web page |
| [OPERATIONS.md](OPERATIONS.md) | Support, recovery, logs, diagnostics |
| [SECURITY.md](SECURITY.md) | Threat model, controls, accepted risks |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, layering rules, test conventions |
| [ROADMAP.md](ROADMAP.md) | What is worth building next, and what is not |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

## License

MIT — see [LICENSE](LICENSE).
