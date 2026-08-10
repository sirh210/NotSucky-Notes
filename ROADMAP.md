# Roadmap

Where the project stands and what would be worth doing next. Ordered by value
per unit of risk, not by how interesting the work is.

## Where it stands

Everything in the [audit](AUDIT.md) is fixed and every recommendation from it
is implemented. The application starts, the storage layer is crash-safe and
recoverable, 408 tests run on two platforms and four Python versions, and
lint, types, and a dependency audit gate every push.

This is a finished, maintainable single-user desktop application. Nothing
below is required to keep using it.

## Near term — small, safe, clearly useful

### 1. Markdown preview toggle
Notes are plain text. A read-mode toggle rendering headings, lists, and links
via `QTextDocument.setMarkdown` is roughly a day's work and touches only
`NoteWidget`. Keep the stored file plain text so nothing is locked in.

### 2. Export
"Export all notes" to a folder of `.md` files or a single zip. The backup
format already does most of this; the gap is a user-facing action and a
choice of format. Reduces the cost of ever leaving this app, which is the
main thing that makes a notes app safe to adopt.

### 3. A trash view in the UI
`Ctrl+Z` covers the last delete, and the files sit in `notes/.trash/` for 30
days, but recovering an older one currently means opening a file manager. A
simple list with restore and "empty trash" would close that gap. The service
layer (`list_trash`, `restore_from_trash`, `empty_trash`) is already built and
tested — this is UI only.

### 4. Pinned notes
One boolean on the model, a sort key ahead of `order`, and a toggle in the
title bar. Frequently requested of every notes application ever written.

## Medium term — worth doing, more design needed

### 5. Tags or folders
The flat list is fine at 50 notes and tiring at 500. Tags fit the storage
model better than folders: a `tags: list[str]` field, a filter chip row, and
`filter_notes` extended to match them. Folders would mean a directory
hierarchy and a migration.

### 6. Full-text search that scales
`filter_notes` is a linear scan over in-memory notes: ~1 ms for 2,000 notes,
so it is not a problem yet. Past roughly 10,000 notes it will be, and SQLite
FTS5 over a shadow index would be the answer. **Do not do this before the
numbers demand it** — it would trade the current "your notes are just JSON
files" property for speed nobody needs yet.

### 7. Signed installers
A `.msi` and a `.dmg` via PyInstaller, so installing does not require Python.
The build is straightforward; the real cost is code-signing certificates,
without which both operating systems show scary warnings.

### 8. Configurable retention and backup policy
Trash retention (30 days), backup count (10), and backup interval (daily) are
constants. They should be a small settings file once anyone disagrees with a
default.

## Long term — only with a clear reason

### 9. Sync across machines
One JSON file per note already syncs through Dropbox, Syncthing, or git today,
and that covers most of the need. Doing it *properly* means conflict
resolution, which means either last-write-wins (lossy) or CRDTs (a large
project). Recommend documenting the third-party approach rather than building
one.

### 10. Encryption at rest
Notes are plaintext. An encrypted volume with `NOTSUCKY_NOTES_DIR` pointed at
it solves this today without adding a key-management problem — which is the
part that actually loses people's data.

### 11. Mobile or web companion
A different application sharing only the file format. Out of scope for a Qt
desktop app; mentioned because it is the usual next request.

## Deliberately not planned

| Idea | Why not |
| --- | --- |
| Rich text / WYSIWYG | Turns a readable JSON store into an opaque one. Markdown gets most of the benefit for none of the cost. |
| Cloud accounts | Introduces auth, a server, privacy obligations, and running costs to an application that currently has none. |
| Plugin system | No second developer and no demand. A plugin API is a permanent compatibility promise. |
| A database | The whole point is that a note is a file you can read, diff, and sync. SQLite would only be justified by the FTS problem in item 6. |

## Health metrics worth watching

| Metric | Now | Act when |
| --- | --- | --- |
| Test count / coverage | 408 / 92% | Coverage drops below the 90% CI floor |
| Cold start, 2,000 notes | ~95 ms | Over 500 ms |
| Grid first paint | ~9 ms | Over 100 ms |
| `load_all`, 2,000 notes | ~85 ms | Over 500 ms — that is when the FTS index earns its keep |
| Runtime dependencies | 1 | Any addition needs a reason in the PR |
