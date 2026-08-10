# Operations & Support Runbook

For whoever has to answer "it broke, what now?" — including future you.

## First response: get the diagnostics

```bash
notsucky-notes-cli --diagnostics
```

Prints versions, every path in use, and how many notes, trash entries, and
backups exist. It contains **no note titles or contents**, so it is safe to
paste into a public issue. Nearly every question below is answered by this
output plus the log file.

## Where everything lives

| What | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Notes | `%LOCALAPPDATA%\NotSucky Notes\notes` | `~/Library/Application Support/NotSucky Notes/notes` | `$XDG_DATA_HOME/notsucky-notes/notes` |
| Trash | `…/notes/.trash` | same | same |
| Backups | `…/NotSucky Notes/backups` | same | same |
| Logs | `…/NotSucky Notes/logs/notsucky.log` | same | same |

Override the notes location with `NOTSUCKY_NOTES_DIR` or `--notes-dir`; the
flag wins. The dashboard header always shows the path actually in use.

A note is one JSON file named `<id>.json`. Nothing else is needed to read
them — any text editor will do, and that is deliberate.

## Recovery, in increasing order of desperation

### A note was deleted by accident
1. `Ctrl+Z` in the dashboard restores the most recent deletion.
2. Older ones: look in `notes/.trash/`. Files are named
   `<id>.<unix-time>.json`. Copy one back into `notes/` and rename it to
   `<id>.json`. Restart or press `F5`.
3. Deleted more than 30 days ago: it has been swept. Go to backups.

### Restore from a backup
```bash
notsucky-notes-cli --list-backups
```
Snapshots are plain zips of the notes directory. Unzip the one you want over
`notes/`. To restore without overwriting anything current, unzip elsewhere and
copy across only the files you need.

### The notes directory is empty after an upgrade
Almost certainly the 1.0 → 1.1 storage move. Versions before 1.1 stored notes
inside the project directory; 1.1 copies them into the user data directory on
first launch. Check:
- the header path, and `--diagnostics`;
- the old location — the originals were **copied**, not moved, so they are
  still there;
- `notes/.migrated-from-legacy`. Deleting that marker makes the import run
  again on next launch.

### A note will not load
The loader skips unreadable files rather than failing, and logs each one:
```
Skipping unreadable note file 1a2b3c4d.json: ...
```
Common causes: invalid JSON after a hand-edit, or a file over 8 MB (the size
guard). Fix the JSON, or recover the note from `.trash`/a backup.

### A note window is off-screen
It cannot be, as of 1.1 — positions are clamped to the attached displays on
open and on drag release. If it happens, delete the `x`/`y` fields from the
note's JSON and reopen.

## Diagnosing a problem

### Get a verbose log
```bash
notsucky-notes --log-level DEBUG
```
Logs go to the console *and* to `logs/notsucky.log` (rotating, 3 × 1 MB).
Qt's own warnings are routed into the same file, so a rendering or platform
problem shows up there rather than on a console nobody sees.

Timings for the slow-capable startup steps are logged at INFO:
```
Startup maintenance took 12 ms
Dashboard startup took 94 ms
```
If a user reports slow startup, those two lines localise it immediately.

### The app crashed
Uncaught exceptions are logged at CRITICAL with a full traceback under the
`notsucky.crash` logger, and the user gets a dialog naming the log file.
Search the log for `Unhandled`.

### "It says ⚠ not saved"
A write failed. The status bar carries the reason; the log has the
`StorageError`. Usual causes: the notes directory is read-only, the disk is
full, or a sync client has the file locked. Notes are written atomically, so
the previous version on disk is intact.

## Routine maintenance

Nothing is required. For reference, on each launch the app purges trash older
than 30 days and takes a backup if the newest is over a day old.

To back up on a schedule instead, the CLI needs no display:
```bash
# cron: hourly snapshots
0 * * * * /path/to/venv/bin/notsucky-notes-cli --backup-now
```
Ten snapshots are kept; older ones are pruned automatically.

To disable the startup backup: `notsucky-notes --no-backup`.

## Upgrading

```bash
git pull && pip install -e .
```
The note format only ever gains fields, and unknown fields are ignored on
load, so a newer file opens in an older build with the new fields dropped.
Take a backup first anyway: `notsucky-notes-cli --backup-now`.

## Escalation

Include the `--diagnostics` output, the relevant part of
`logs/notsucky.log`, and what you were doing. Never attach a note file
containing anything private — the id from the log is enough to correlate.
