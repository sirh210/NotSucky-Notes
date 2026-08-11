"""Statistics over a set of notes.

Pure computation, no Qt: the numbers are worth testing on their own, and the
same figures feed both the dialog and the ``--stats`` console output.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from notsucky.models.note import Note

#: Days of history the activity chart covers.
ACTIVITY_DAYS = 14

#: How many entries the ranked breakdowns keep.
TOP_TAGS = 6


def _to_local_date(timestamp: str) -> date | None:
    """Parse an ISO timestamp into a local calendar date.

    v1.0 wrote naive local timestamps and 1.1 onward writes UTC, so both
    have to land on the right day.
    """
    try:
        moment = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone().date()


def word_count(text: str) -> int:
    return len(text.split())


@dataclass(frozen=True)
class Statistics:
    """Everything the dashboard reports, computed once."""

    total_notes: int = 0
    total_characters: int = 0
    total_words: int = 0
    empty_notes: int = 0
    minimized_notes: int = 0
    average_characters: int = 0

    longest_note: Note | None = None
    newest_note: Note | None = None
    oldest_note: Note | None = None

    colors: list[tuple[str, int]] = field(default_factory=list)
    tags: list[tuple[str, int]] = field(default_factory=list)
    distinct_tags: int = 0
    untagged_notes: int = 0

    #: (date, created, updated) per day, oldest first, gaps filled with zeros.
    activity: list[tuple[date, int, int]] = field(default_factory=list)

    trash_count: int = 0
    backup_count: int = 0

    @property
    def most_used_color(self) -> str | None:
        return self.colors[0][0] if self.colors else None

    @property
    def busiest_day(self) -> tuple[date, int] | None:
        """The day with the most edits, or None if nothing happened."""
        if not self.activity:
            return None
        day, _created, updated = max(self.activity, key=lambda row: row[2])
        return (day, updated) if updated else None

    @property
    def peak_activity(self) -> int:
        """The tallest bar, so the chart can scale itself."""
        return max((updated for _d, _c, updated in self.activity), default=0)


def compute(
    notes: list[Note],
    *,
    days: int = ACTIVITY_DAYS,
    trash_count: int = 0,
    backup_count: int = 0,
    today: date | None = None,
) -> Statistics:
    """Summarise ``notes``.

    ``today`` is injectable so the activity window is testable without
    freezing the clock.
    """
    if not notes:
        return Statistics(
            activity=_empty_activity(days, today),
            trash_count=trash_count,
            backup_count=backup_count,
        )

    characters = sum(len(n.content) for n in notes)
    words = sum(word_count(n.content) for n in notes)

    color_counts = Counter(n.color for n in notes)
    tag_counts: Counter[str] = Counter()
    for note in notes:
        tag_counts.update(note.tags)

    created_per_day: Counter[date] = Counter()
    updated_per_day: Counter[date] = Counter()
    for note in notes:
        created = _to_local_date(note.created_at)
        if created:
            created_per_day[created] += 1
        updated = _to_local_date(note.updated_at)
        if updated:
            updated_per_day[updated] += 1

    end = today or datetime.now(timezone.utc).astimezone().date()
    window = [end - timedelta(days=offset) for offset in range(days - 1, -1, -1)]

    return Statistics(
        total_notes=len(notes),
        total_characters=characters,
        total_words=words,
        empty_notes=sum(1 for n in notes if not n.content.strip()),
        minimized_notes=sum(1 for n in notes if n.minimized),
        average_characters=round(characters / len(notes)),
        longest_note=max(notes, key=lambda n: len(n.content)),
        newest_note=max(notes, key=lambda n: n.created_at or ""),
        oldest_note=min(notes, key=lambda n: n.created_at or ""),
        # Ranked by count, then by name so equal counts are not arbitrary.
        colors=sorted(color_counts.items(), key=lambda kv: (-kv[1], kv[0])),
        tags=sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_TAGS],
        distinct_tags=len(tag_counts),
        untagged_notes=sum(1 for n in notes if not n.tags),
        activity=[
            (day, created_per_day.get(day, 0), updated_per_day.get(day, 0))
            for day in window
        ],
        trash_count=trash_count,
        backup_count=backup_count,
    )


def _empty_activity(days: int, today: date | None) -> list[tuple[date, int, int]]:
    end = today or datetime.now(timezone.utc).astimezone().date()
    return [(end - timedelta(days=offset), 0, 0) for offset in range(days - 1, -1, -1)]


def collect() -> Statistics:
    """Compute statistics from the notes on disk, trash and backups included."""
    from notsucky.services import backup
    from notsucky.services.file_manager import FileManager

    return compute(
        FileManager.load_all(),
        trash_count=len(FileManager.list_trash()),
        backup_count=len(backup.list_backups()),
    )


def format_report(stats: Statistics | None = None) -> str:
    """Render the figures as plain text.

    This doubles as the accessible table view of the charts: every number in
    the dialog is available here without a display.
    """
    stats = collect() if stats is None else stats
    lines = [
        "Notes",
        f"  total              : {stats.total_notes}",
        f"  words              : {stats.total_words:,}",
        f"  characters         : {stats.total_characters:,}",
        f"  average length     : {stats.average_characters:,} characters",
        f"  empty              : {stats.empty_notes}",
        f"  minimized          : {stats.minimized_notes}",
        f"  in trash           : {stats.trash_count}",
        f"  backups            : {stats.backup_count}",
    ]

    if stats.longest_note is not None:
        longest = stats.longest_note
        lines += [
            "",
            "Longest note",
            f"  {longest.title or 'Untitled'} — {len(longest.content):,} characters",
        ]

    if stats.colors:
        lines += ["", "Colours"]
        width = max(len(name) for name, _ in stats.colors)
        for name, count in stats.colors:
            lines.append(f"  {name.ljust(width)} : {count}")

    lines += ["", "Tags", f"  distinct           : {stats.distinct_tags}",
              f"  untagged notes     : {stats.untagged_notes}"]
    for name, count in stats.tags:
        lines.append(f"  {name} : {count}")

    busiest = stats.busiest_day
    lines += ["", f"Activity (last {len(stats.activity)} days)"]
    if busiest:
        lines.append(f"  busiest day        : {busiest[0].isoformat()} ({busiest[1]} edits)")
    for day, created, updated in stats.activity:
        if created or updated:
            lines.append(f"  {day.isoformat()}  created {created}  edited {updated}")

    return "\n".join(lines)
