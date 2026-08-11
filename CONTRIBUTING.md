# Contributing

## Getting set up

```bash
git clone https://github.com/sirh210/NotSucky-Notes.git
cd NotSucky-Notes

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
pytest
```

If `pytest` is green you have a working environment. On a headless Linux box
you also need Qt's system libraries:

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon-x11-0 libdbus-1-3
export QT_QPA_PLATFORM=offscreen
```

## Before you push

Everything CI checks, you can run locally in about twenty seconds:

```bash
ruff check .          # lint and import order
mypy notsucky         # type check
pytest                # the full suite
pytest --cov=notsucky --cov-report=term-missing
```

## How the code is organised

The layering is the load-bearing part of the design. Keep it:

```
views/     Qt widgets. Call services. Never touch the filesystem.
services/  Persistence and business logic. Import no Qt.
models/    Plain data with validation. No I/O, no Qt.
utils/     Constants and pure helpers. Unit-testable without a display.
```

`services/` importing Qt, or `views/` calling `open()`, is the change most
likely to be sent back — that separation is what makes most of the suite
runnable without a display.

## Rules with reasons

Each of these exists because breaking it caused a real bug. The
[audit](AUDIT.md) has the full account.

1. **Never capture the storage path as a module constant.** Call
   `notes_dir()`. A module-level `NOTES_DIR` is frozen at import time by every
   module that imports it, which made the location impossible to override and
   pointed the app at a directory the user's notes were not in.
2. **All writes go through `FileManager.save_note`.** It writes to a temporary
   file and `os.replace`s it into position. A plain `open(path, "w")`
   truncates first, so an interrupted write destroys the note.
3. **Never swallow a `StorageError`.** It must reach the UI. A save that
   silently fails is a user typing into a void.
4. **Nothing may delete a note the user did not delete.** Deletion moves the
   file into the trash, which has no expiry. Do not add a sweep, a retention
   timer, a "tidy up" task, or a cleanup of files the loader could not parse.
   `purge_note`, `purge_trash`, and `empty_trash` exist for an explicit user
   request only, and nothing may call them automatically.
5. **No limit may shorten text that already exists.** `MAX_CONTENT_LENGTH` and
   `MAX_TITLE_LENGTH` bound how far *new* input can grow a note. Truncating on
   load looks harmless and is written back by the next save as a real
   deletion. Enforce ceilings in the editor, never in the model or service.
6. **No networking, ever.** The package imports no network library and there
   is no sign-in. A test walks the AST of every module and fails on `socket`,
   `urllib`, `requests`, `QtNetwork`, and friends. Keep it that way.
7. **Never log note titles or content.** Ids and counts only. Two tests
   enforce this by writing a secret into a note and searching the log.
8. **A `QWidget` subclass needs `WA_StyledBackground`** to paint its own
   background colour. Without it the widget renders transparent, which is not
   visible to any logic test.
9. **Do not give a widget its own stylesheet inside a loop.** Qt re-parses CSS
   per widget; that was 80% of the cost of building the grid. Add rules to
   `CARD_STYLESHEET` and select on a property instead.
10. **Scope every Qt stylesheet with a selector.** A selector-less sheet such
    as `setStyleSheet("background: transparent")` applies to the widget *and
    every descendant*, which once blanked every card in the grid.

## Tests

- Every bug fix gets a test named after the bug, not after the method.
- An autouse fixture repoints storage at a temporary directory, so tests can
  never read or write real notes. Do not bypass it.
- GUI tests use `pytest-qt`. Prefer asserting observable behaviour — pixels,
  emitted signals, files on disk — over internal state.
- Performance guards live in `tests/test_performance.py`. Their thresholds are
  deliberately loose; if one fails, find the cause before raising the limit.
- Documentation is tested too. `tests/test_docs.py` fails when the README
  describes a module, shortcut, or flag that does not exist.

## Commits and pull requests

Explain *why* in the body — the diff already shows what. Keep the subject
under about 70 characters. CI must be green: lint, types, dependency audit,
and the suite on Linux and Windows across Python 3.10–3.13.
