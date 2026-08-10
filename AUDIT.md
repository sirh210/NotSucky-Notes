# NotSucky Notes — Production Readiness Audit

**Audited version:** 1.0.0 · **Delivered version:** 1.1.0 · **Date:** 2026-08-10
**Scope:** the whole repository — application code, persistence, packaging, tests, tooling, docs.

---

## Verdict

The audited version **could not start.** `notsucky/views/card_widget.py` raised
`ImportError` at import time, and the dashboard imports it on every grid
refresh — including the one in its constructor. Behind that blocker sat a
second one (`NameError` on `QSizePolicy`), and behind those, a storage layer
pointed at a directory the user's notes were not in.

The test suite did not catch any of it: 8 tests failed and 7 errored before
this audit, there was no GUI coverage at all, and the tests that did run were
reading and writing the *real* notes directory.

| | Before | After |
| --- | --- | --- |
| Application starts | ❌ `ImportError` | ✅ |
| Tests | 8 failed, 7 errored, 11 passed | ✅ 408 passed |
| Coverage | not measurable | 92% |
| Lint (`ruff`) | 104 errors | ✅ clean |
| Wheel builds | ❌ invalid build backend | ✅ builds and installs |
| Installed package imports | ❌ 4 subpackages missing | ✅ |
| Notes visible to the app | ❌ wrong directory | ✅ + migrated |

Findings are grouped by severity. Every one listed is fixed unless marked
otherwise.

---

## 1. Blockers — the application could not run

### 1.1 `QMouseEvent` imported from the wrong Qt module
`card_widget.py:8` — `from PySide6.QtCore import Qt, QMouseEvent, Signal`.
`QMouseEvent` lives in `QtGui`. This raised `ImportError` the moment anything
imported the module, which `DashboardWindow._refresh_grid` does
unconditionally. **The application was 100% non-functional.**

### 1.2 `QSizePolicy` used but never imported
`card_widget.py:40` — `self.setSizePolicy(QSizePolicy.Expanding, ...)` with no
import. A second, independent hard failure sitting immediately behind 1.1.

### 1.3 Invalid PEP 517 build backend
`pyproject.toml:3` — `build-backend = "setuptools.backends._legacy:_Backend"`.
No such module. `pip install .` and any wheel build failed outright.

### 1.4 Four subpackages had no `__init__.py`
`models/`, `services/`, `utils/`, and `views/` contained no `__init__.py`.
They resolved in a source checkout only through implicit namespace packages;
`[tool.setuptools.packages.find]` had no `include` filter and would have
swept in `tests` and `notes` while an install missed the real code.

**Fixed:** correct imports, `setuptools.build_meta`, `__init__.py` in every
subpackage, `include = ["notsucky*"]`. Verified by building a wheel and
importing all subpackages from a clean virtualenv.

---

## 2. Critical — data loss and data location

### 2.1 Notes were stored where the user could not see them
`utils/constants.py:9` set `PROJECT_ROOT = Path(__file__).resolve().parent.parent`
— that is the **package** directory, not the project root. `NOTES_DIR`
therefore resolved to `notsucky/notes`, while the user's two real notes lived
in `./notes`. The app would have shown an empty dashboard. For an installed
package it would have written notes into `site-packages`, where the next
upgrade deletes them.

### 2.2 A third, CWD-dependent location
`main.py:12` ran `os.makedirs("notes", exist_ok=True)` at import time —
relative to the working directory, and disagreeing with 2.1.

### 2.3 The storage path could not be overridden consistently
`file_manager.py:12` bound `NOTES_DIR` at module import, while
`models/note.py:14` resolved it lazily on purpose ("to support testing
monkeypatches"). The two disagreed under any override: `save_note` wrote to
the patched directory via `note.file_path` while `load_by_id`, `load_all`, and
`delete_note` used the original. This is why the baseline tests both failed
*and* touched the user's real notes.

**Fixed:** a single `utils/paths.py` resolver — explicit override →
`NOTSUCKY_NOTES_DIR` → per-platform user data directory — that everything
calls as a function. Notes now live in `%LOCALAPPDATA%\NotSucky Notes\notes`
(or the XDG / Application Support equivalent), with a **one-time copy**
migration from either legacy location. Originals are left in place as a
backup, and a marker file stops the import from re-running after you delete a
note. Verified end to end: both real notes were imported and rendered.

### 2.4 Writes were not atomic
`file_manager.py:32` — `open(path, "w")` truncates the file before writing.
A crash, a power loss, or a full disk mid-write destroyed the note, and the
loader then discarded the wreckage as "corrupt".

**Fixed:** write to a temporary file in the same directory, `fsync`, then
`os.replace`. A failed write now leaves the previous version completely
intact — covered by a test that injects an `OSError` into `os.replace`.

### 2.5 Save failures were invisible to the user
Errors were logged and swallowed. The user kept typing into a note that was no
longer reaching the disk.

**Fixed:** `StorageError` propagates to the view, the note's status bar shows
`⚠ not saved`, and the dashboard status bar shows the reason.

### 2.6 No path-traversal guard on note ids
Note ids became file names with no validation. A hand-edited or hostile JSON
file with `"id": "../../.bashrc"` would be written outside the notes
directory.

**Fixed:** ids are validated against `[A-Za-z0-9_-]{1,64}`, repaired on load,
and rejected in `FileManager.path_for`.

---

## 3. High — functional defects

### 3.1 Runaway window drag
`note_widget.py:142-146` re-applied a delta measured from the *original*
press position on every move event without re-anchoring, so the offset
compounded. **This bug is present in your saved data:**
`notes/505e8a20.json` holds `"x": -45088, "y": 33945`.

### 3.2 Off-screen positions were restored blindly
`note_widget.py:70-71` moved the window to the saved coordinates with no
bounds check, so the note in 3.1 opened ~45,000 px off-screen and could never
be reached again.

**Fixed:** drag anchors on the cursor-to-origin offset (constant, cannot
compound); position is clamped to the actual screen layout on both restore and
drag release. The stored `-45088` note now opens on screen — verified.

### 3.3 Notes could not be dragged at all
`note_widget.py:139` guarded the drag with `not self.childAt(event.pos())`.
This is inverted: a press only *reaches* the window handler when a
non-interactive child ignored it, which is exactly when `childAt` is
non-`None`. The guard rejected precisely the presses that should drag.

**Fixed:** an explicit drag-handle test that walks up from the child under the
cursor and refuses only genuinely interactive controls. Because the title
field stretches across the whole bar and left almost nothing to grab, a
dedicated `⠿` drag handle was added.

### 3.4 Notes could not be resized
The window is `Qt.FramelessWindowHint`, which removes the native resize
border, and nothing replaced it — despite the README's "**Resizable** floating
windows … resize freely". The model had no width/height fields either, so any
size would have been lost on close.

**Fixed:** a `QSizeGrip` in the status bar, plus `width`/`height` persisted on
the note.

### 3.5 Auto-save was not debounced
`note_widget.py:158` called `QTimer.singleShot(1000, ...)` on **every**
`textChanged`. Typing 200 characters scheduled 200 timers and produced 200
full-file writes a second later. `_on_title_changed` had no debounce at all —
one disk write per keystroke.

**Fixed:** one restartable `QTimer` per window; a burst of typing produces
exactly one write. Covered by a test asserting zero writes mid-burst.

### 3.6 Cards rendered with no background
A `QWidget` **subclass** ignores `background-color` in its own stylesheet
unless `WA_StyledBackground` is set. The v1.0 refactor turned the card from a
plain `QWidget` into a subclass and inherited this: every card painted
transparent, leaving pale text on the dark dashboard.

Not visible to any logic test — found by rendering the app and looking at it.
**Fixed** on both `CardWidget` and `NoteWidget`, with regression tests that
assert real pixel colors.

### 3.7 Minimized notes were stranded after a restart
`DashboardWindow.__init__` never populated `_minimized_ids` from the persisted
`minimized` flags (the monolith it replaced did). The dock came up empty and
minimized notes were unreachable from it.

### 3.8 Restoring a note never cleared its minimized flag
`restore_note` (`dashboard.py:254`) removed the id from the in-memory list but
never wrote `minimized = False`, so the note stayed flagged on disk forever.

### 3.9 Hidden note windows leaked and could be duplicated
`open_note` tested `note.id in self._open_notes and ...isVisible()`. For a
minimized (hidden) note both branches fell through, so a second `NoteWidget`
was constructed and overwrote the dictionary entry — orphaning the first,
which still held the same `Note` object.

### 3.10 Deleting an open note resurrected it
`delete_note` only cleaned up `_open_notes` when the widget was *visible*. A
hidden widget survived deletion, and the next auto-save tick wrote the deleted
note straight back to disk.

**Fixed (3.7–3.10):** the dock is rebuilt from disk at startup and pruned of
notes that no longer exist; restore clears the flag in memory, on disk, and in
the dock; a `_live_widget` helper drops references whose C++ object is gone;
deletion tears the window down (with signals blocked) *before* removing the
file. All four have named regression tests.

### 3.11 The dashboard never closed its note windows
There was no `closeEvent`. Note windows are top-level `Qt.Tool` windows, so
closing the dashboard left them alive — keeping the process running and losing
every unflushed edit.

**Fixed:** `closeEvent` stops the timers, flushes every open note, and closes
them.

### 3.12 Advertised drag-to-reorder did not exist
The README and the `pyproject.toml` description both promise a
"drag-to-reorder grid". `CardWidget` called `setAcceptDrops(True)` and
implemented no drag or drop handlers. (The monolith's attempt could not have
worked either — see §7.)

**Fixed:** implemented properly. Cards are drag sources and drop targets with
a dashed drop indicator, an `order` field persists the arrangement, and
`sort_for_display` sorts by manual order with recency as the tie-break.
Reordering is refused while a filter is active, because writing positions
derived from a filtered subset would scramble the full list.

### 3.13 Non-deterministic note placement
`_random_position` used `hash(self.note.id)`. Python salts string hashing per
process, so a note without a saved position landed somewhere different on
every launch, with no bound keeping it on screen.

**Fixed:** a deterministic cascade derived from the id, clamped to the screen.

---

## 4. Medium — correctness and performance

| # | Finding | Fix |
| --- | --- | --- |
| 4.1 | `delete_note` returned `True` unconditionally, contradicting its own docstring ("True if it existed"). | Returns the real outcome; `StorageError` on a genuine failure. |
| 4.2 | Search re-read and re-parsed **every note file on every keystroke** (`textChanged` → `_refresh_grid` → `load_all`). | Notes are cached in memory; filtering is a pure function; input is debounced 150 ms. |
| 4.3 | `_update_dock_ui` called `load_by_id` once per dock entry, per rebuild. | Served from the in-memory list. |
| 4.4 | Naive local timestamps compared as strings — ordering breaks across a DST change or a timezone move. | Timezone-aware UTC throughout; v1 naive timestamps still parse. |
| 4.5 | No length limits on title or content; a large paste became an unbounded file. | 200 / 1,000,000 characters, enforced in the model, the service, and the editor. |
| 4.6 | `Note.from_dict` trusted its input; one malformed field took down the whole grid load. | Every field is coerced or defaulted; unknown keys dropped; non-object JSON rejected. |
| 4.7 | `FileManager.search` was dead code — the dashboard reimplemented the same filter inline. | One `filter_notes` helper used by both. |
| 4.8 | `CardWidget` declared `open_requested`/`delete_requested` signals, then used constructor callbacks instead. | Signals only, wired by the dashboard. |
| 4.9 | Fixed 4-column grid regardless of window width, despite "responsive resizing" in the code comments. | Column count derives from the viewport (1–6), via a pure function with its own tests. |
| 4.10 | Colour swatches captured `scheme` in a closure at construction; after a colour change the "current" marker pointed at the old colour and one swatch stayed permanently inert. | A real `ColorDot` button class that re-marks the selected colour on every scheme change. |
| 4.11 | CSS typo `border-top-right-right-radius` — silently ignored, corner never rounded. | Corrected. |
| 4.12 | Body/foreground contrast ≈2.3:1 (`#F57F17` on `#FFF9C4`), below WCAG AA. | Foreground colours darkened to ≥7:1 while keeping the palette recognisable. |
| 4.13 | No keyboard access, no accessible names, no tooltips. | Ctrl+N/F/W/M/S, F5, Esc; accessible names on every control; tooltips throughout. |
| 4.14 | Logging configured at import time; no log file. | Configured in `main()`; rotating log in the user data directory; `--log-level`. |
| 4.15 | `os.makedirs` ran as an import side effect. | Importing the package now does nothing. |

---

## 5. Test suite

The suite was actively misleading — it reported confidence it had not earned.

* **8 failures, 7 errors** at baseline, none of which were app bugs being
  correctly reported; they were defects in the tests themselves.
* `test_search_by_title` asserted `results[0].title == "Note Python Notes"` —
  a value the code could never produce.
* `test_note_service.py:16` monkeypatched `note_module.NOTES_DIR`, an
  attribute that does not exist on that module → `AttributeError` errored out
  all 7 tests in the file.
* `conftest.py` created `tests/__init__.py` as a side effect of collection.
* **Tests read and wrote the user's real notes directory** (see §2.3). Running
  `pytest` risked the user's data.
* **Zero GUI coverage** — which is why two import-time blockers shipped.

**Delivered:** 408 tests, 92% coverage, isolated by an autouse fixture that
repoints storage at a per-test temporary directory and suppresses the legacy
import. Includes GUI tests via `pytest-qt` covering the grid, filtering, the
dock, open/close/minimize/restore/delete lifecycles, drag-to-reorder,
debounced saving, storage-failure reporting, off-screen clamping, and the
pixel-level background regression from §3.6. Named regression tests exist for
each of §3.1, §3.3, §3.6, §3.7, §3.8, §3.9, §3.10.

---

## 6. Tooling, packaging, docs

* `requirements.txt` mixed `pytest` into runtime dependencies → split into
  `requirements.txt` / `requirements-dev.txt`.
* README claimed MIT with no `LICENSE` file → added, plus PEP 639 metadata.
* No `.gitignore`; `.pytest_cache/` and `__pycache__/` were sitting in the
  tree. **The project is not a git repository at all** — see Recommendations.
* Dead imports (`Iterator`, `QFont`, `json`, `logging`), an unreachable
  `Qt.QPoint` annotation (not a real type), and a `Note` docstring describing
  the class as "Immutable-ish" when it is a fully mutable dataclass.
* `ruff` reported 104 errors; the config selected no rule set beyond the
  default. Now `E,F,W,I,UP,B,C4,SIM,RUF` and **clean**.
* The README documented features that did not exist (reorder, resize) and a
  storage path that was wrong. Rewritten to match the shipped behaviour.
* A GUI entry point on Windows cannot write to the console, so `--help` and
  `--version` were invisible → added a `notsucky-notes-cli` console alias and
  `python -m notsucky`.

---

## 7. Removed code

`main.py` in the repository root was a 22 KB copy of the original
single-file "Sticky Notes v6", fully superseded by the `notsucky/` package and
still being shipped. It had its own fatal bugs — `QGridLayout.rowWidget()` and
`columnWidget()` do not exist in Qt, `event.mimeData.data(...)` is missing a
call, `drag.exec_()` is the removed Qt5 spelling, and `QDrag` was never
imported — so its drag-to-reorder raised on first use. It also accounted for
68 of the 104 lint errors.

Moved to `archive/` rather than deleted, because there is no version control
to recover it from. `_dump.py` and `_dump.py.tmp` (debugging leftovers) went
with it. `archive/` is excluded from linting and from the wheel.

---

## 8. Recommendations — all implemented

These were originally logged as "not done, your call". They were subsequently
requested and are now in the codebase.

### 8.1 Version control
`git init`, full tree committed, pushed to
[`sirh210/NotSucky-Notes`](https://github.com/sirh210/NotSucky-Notes). This was
the largest remaining risk: no history, no diff, no way to recover a mistake.
`archive/` was included in the initial commit so git holds a copy of the
superseded monolith, then removed in the commit after — recoverable from
history, absent from the working tree.

### 8.2 Continuous integration
`.github/workflows/ci.yml` runs `ruff` plus the full suite on **Linux and
Windows across Python 3.10–3.13**, then builds the wheel, runs `twine check`,
and installs it into a clean virtualenv to confirm every subpackage imports —
which is precisely the failure mode of §1.4. GUI tests run under
`QT_QPA_PLATFORM=offscreen` with the `libegl1` family installed on Linux
runners. Every blocker in §1 would have been caught by this job on the commit
that introduced it.

### 8.3 Undo for deletion
Deletion no longer unlinks. Notes move into `notes/.trash/` under a
`<id>.<unix-time>.json` name, `Ctrl+Z` restores the most recent, and a startup
sweep purges anything older than 30 days. Two details worth noting: the
deletion time lives in the *file name* rather than the mtime, which archivers
and sync tools do not preserve; and restoring a note whose id has since been
taken by a new note assigns a fresh id instead of overwriting the newer one.

### 8.4 Backups
`services/backup.py` writes dated zip snapshots to a `backups/` directory
beside the notes — at most one a day, ten kept. The archive is built under a
`.part` name and renamed into place, so a partial file is never mistaken for a
usable snapshot, and the trash is excluded so restoring cannot resurrect
deleted notes. Restore skips any entry containing a path separator, so a
tampered archive cannot write outside the notes directory. `--backup-now` and
`--list-backups` run without a QApplication, which makes them usable from cron
or Task Scheduler.

### 8.5 Application icon
Drawn at runtime in `views/icon.py` at seven sizes — no binary asset, no
package-data entry, and no blur from scaling one bitmap. Rules are dropped
below 24 px where they would turn to mud. Verified on both light and dark
grounds.

---

## 9. Follow-up review (v1.2.0)

A second pass covering security, performance, observability, code quality, and
documentation. Everything here was **measured before it was changed** — the
numbers are from this machine, not estimates.

### 9.1 Security — three real holes, closed

| Finding | Before | After |
| --- | --- | --- |
| **Unbounded read.** A note file was read entirely into memory before the 1,000,000-character cap applied. One 60 MB file was a 60 MB allocation at startup; a directory of them was an OOM crash. | 60 MB file: `load_all` 114 ms, file read in full | Skipped over 8 MB: **2 ms**, nothing allocated |
| **Zip bomb.** `restore_backup` extracted whatever an archive contained. | 199 KB archive → **200 MB written** in 332 ms | **0 bytes written**, refused in 11 ms |
| **World-listable data.** The notes directory took the default mode, letting any local account list note titles. | `0755` on POSIX | `0700` on POSIX; skipped on Windows, where ACLs already restrict it and POSIX modes are cosmetic |

Checked and found already sound: path traversal (ids validated, repaired on
load, rejected at the path boundary), deserialization (no `pickle`/`eval`,
every field coerced, unknown keys dropped), and logging — no note title or
body reaches a log record, now enforced by tests that plant a secret and
search the captured output.

Accepted, not fixed: symlinks inside the notes directory are followed on read.
Blocking that would break legitimate setups, and anyone who can create files
in your data directory already has your account. Documented in
[SECURITY.md](SECURITY.md).

### 9.2 Performance — the grid, not the disk

Measured at 10/100/500/2,000 notes before touching anything. I/O was never the
problem; **building widgets was**.

| At 2,000 notes | Before | After |
| --- | --- | --- |
| Grid build (blocking first paint) | 2,046 ms | **9 ms** |
| Grid build (total, all cards) | 2,046 ms | **365 ms** |
| Dashboard startup | 1,603 ms | **93 ms** |
| `load_all` | 83 ms | 89 ms (unchanged — never the bottleneck) |
| Filter keystroke | 1.1 ms | 1.2 ms (already in-memory) |

Two causes, both fixed:

1. **Per-widget stylesheets.** Qt re-parses CSS for every widget that carries
   its own. At five `setStyleSheet` calls per card that was ~80% of card
   construction. Cards now set a `noteColor` property against one
   application-scope sheet: **350 µs → 142 µs per card.**
2. **Building everything before painting.** The grid now builds 48 cards —
   more than fills any viewport — then streams the rest in chunks through the
   event loop.

### 9.3 Code quality

`mypy` was added and its findings were real, not ceremony:

- `QApplication.instance()` is typed as, and can be, a `QCoreApplication` with
  no stylesheet at all — an `AttributeError` waiting for a headless run.
- `QLayout.takeAt` can return `None`; two loops assumed otherwise.
- `is_valid_id` is now a `TypeGuard`, so the runtime check and the static type
  cannot drift apart.

Duplication removed: four copies of the same `try/except RuntimeError` dance
around Qt's Python/C++ object lifetime became `views/qt_support.py`, and two
copies of the layout-clearing loop became `clear_layout`.

**Considered and declined:** extracting a `NoteWindowManager` from
`dashboard.py` (600 lines). The class is cohesive and its longest method is 43
lines, so the case rests on file length alone — while the code in question is
the most bug-prone in the application and has just been stabilised. That trade
is not worth making today. The seam is the `_open_notes` dictionary plus the
open/close/minimize/restore methods, if it ever grows further.

### 9.4 Documentation is now tested

`tests/test_docs.py` fails when the docs describe something that does not
exist: a module in the structure tree, a keyboard shortcut, a CLI flag, a
relative link, a version number, or an unreplaced clone-URL placeholder. It
caught three stale claims in the README on its first run.

---

## Still open

Nothing from this audit. Worth considering later, none of it a defect:

- **Signed builds / installers.** Fine as a source install; a packaged
  `.msi`/`.dmg` would need code signing to avoid OS warnings.
- **Sync.** One JSON per note is trivially syncable via Dropbox or Syncthing,
  but concurrent edits from two machines would last-write-wins.
- **Rich text or Markdown rendering.** Notes are plain text by design.
