# Security

## Reporting a vulnerability

Open a [security advisory](https://github.com/sirh210/NotSucky-Notes/security/advisories/new)
rather than a public issue. Expect an acknowledgement within a week.

## Threat model

NotSucky Notes is a local desktop application. It **opens no sockets, makes no
network requests, runs no server, has no accounts or sign-in, and has no users
other than the person at the keyboard.** Most of the OWASP Top 10 describes
attacks on a web application and simply has no surface here.

This is structural, not a promise: the package imports no networking library
at all — no `socket`, `ssl`, `http`, `urllib`, or `requests`, and of Qt only
`QtCore`, `QtGui`, and `QtWidgets`. A test walks the AST of every module and
fails if one appears; another runs a full session with `socket.socket` patched
to raise. There is nothing to authenticate to, so there is no credential to
phish, leak, or store.

What is left is worth taking seriously:

| Adversary | Can do | Cannot do |
| --- | --- | --- |
| A malicious **note file** — hand-edited, synced from another machine, or restored from elsewhere | Supply arbitrary JSON that the app parses at startup | Escape the notes directory or execute code |
| A malicious **backup archive** handed to the user | Supply arbitrary zip content to `restore_backup` | Write outside the notes directory or fill the disk |
| **Another local account** on a shared machine | Read files the filesystem lets it read | Anything, if the data directory is owner-only |
| Someone with **your user account** | Everything | — nothing defends against this, by definition |

## Controls

### Note ids can never escape the notes directory
Ids become file names, so they are validated against `[A-Za-z0-9_-]{1,64}`.
An id failing that check is replaced on load and rejected by
`FileManager.path_for`. A file containing `"id": "../../../etc/passwd"` loads
as a normal note with a fresh id.

### Parsing is total, and never executes anything
`Note.from_dict` reads known keys and coerces or defaults every one of them.
Unknown keys are dropped, so no payload can set an attribute. There is no
`pickle`, no `eval`, no `__reduce__` path — the only deserializer is
`json.loads`, and a non-object document is rejected.

### Reads are bounded
A note is capped at 1,000,000 characters, but the cap only applies *after*
parsing, so the file itself is size-checked first: anything over
`MAX_NOTE_FILE_BYTES` (8 MB) is skipped with a warning. Without that, one
oversized file was a multi-hundred-megabyte allocation during startup, and a
directory of them was an out-of-memory crash.

### Archive restore is hardened three ways
- **Zip slip** — an entry whose name contains a path separator, or is
  absolute, is skipped. Only bare `*.json` names are extracted.
- **Zip bomb** — `ZipInfo.file_size` is checked *before* any bytes are
  written, per entry (16 MB) and in total (2 GB), and the entry count is
  capped. A 199 KB archive declaring 200 MB of output writes nothing.
- **Overwrite** — restoring never replaces an existing note unless
  `overwrite=True` is passed explicitly.

### Writes cannot corrupt existing data
Every save goes to a temporary file in the same directory, is `fsync`ed, and
is moved into place with `os.replace`. An interrupted write leaves the
previous version intact rather than a truncated file. Deletion moves notes to
`.trash` rather than unlinking them.

### Nothing deletes a note but the user
Availability is part of security, and the most likely way to lose a note is
not an attacker — it is the application tidying up. So it does not tidy up.
There is no retention sweep, no expiry, and no cleanup of files the loader
could not parse; an unreadable or oversized file is skipped and left exactly
where it is. `purge_trash`, `empty_trash`, and `purge_note` exist for an
explicit user request and are never called on a timer. Length limits bound
how far new input can grow a note and are never applied to text that already
exists, because truncating on load is written back as a real deletion by the
next save.

### The data directory is owner-only
On Linux and macOS the notes and backup directories are `chmod 0700`, because
the default `0755` lets any local account list your note titles. On Windows
this is skipped deliberately: POSIX modes are cosmetic there, and the
directory inherits `%LOCALAPPDATA%` ACLs, which are already owner-only.

### Logs never contain note contents
Log records carry note **ids**, counts, and paths — never titles or bodies.
Support can follow what happened without the log becoming a plaintext copy of
your notes. Two tests assert this by writing a distinctive secret into a note
and failing if it appears anywhere in the captured log output.

### Dependencies
One runtime dependency: PySide6. CI runs `pip-audit` against the resolved
dependency set on every push, so a published advisory surfaces as a failing
build.

## Accepted risks

**Symlinks inside the notes directory are followed on read.** A symlink placed
in `notes/` will be read as though it were a note. This is deliberate: it
makes legitimate setups work (symlinking a note into a synced folder), and an
attacker who can create files inside your data directory already has your user
account, at which point nothing in this application is a meaningful boundary.

**Notes are stored in plaintext.** There is no encryption at rest. If you need
that, put the notes directory on an encrypted volume and point
`NOTSUCKY_NOTES_DIR` at it.

**Backups are unencrypted zips.** Same reasoning, same remedy.

**No integrity checking of note files.** A note edited outside the app is
trusted as long as it parses. Nothing signs or checksums the store.
