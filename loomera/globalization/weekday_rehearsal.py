"""Phase 6.3: pure read-only preflight for a PROPOSED weekday rekey.

This module imports neither Django models nor a database connection. It does
not approve a migration, inspect live records, or change persisted values.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from loomera.globalization.weekdays import legacy_to_iso_weekday


@dataclass(frozen=True)
class WeekdayRowPreview:
    total_rows: int
    valid_day_rows: int
    invalid_day_rows: int
    invalid_salon_reference_rows: int
    duplicate_salon_day_rows: int
    legacy_counts_saturday_first: tuple[int, ...]
    iso_counts_monday_first: tuple[int, ...]

    @property
    def structurally_clean(self) -> bool:
        """Structural preflight only: NEVER a cutover or release approval."""
        return (
            self.total_rows > 0
            and self.valid_day_rows == self.total_rows
            and self.invalid_salon_reference_rows == 0
            and self.duplicate_salon_day_rows == 0
        )


def preview_legacy_weekday_rows(
    rows: Iterable[tuple[int, int]],
) -> WeekdayRowPreview:
    """Count/validate (salon_id, legacy_day) pairs without storing output IDs.

    Intended for *already authorized, sanitized* fixture data. A pure
    deterministic preview has no permission to query production databases.
    Duplicate rows are counted as excess occurrences, never silently merged.
    """
    seen: set[tuple[int, int]] = set()
    legacy_counts = [0] * 7
    iso_counts = [0] * 7
    total = valid = invalid_day = invalid_salon = duplicates = 0
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            raise TypeError("each row must contain (salon_id, day_of_week)")
        salon_id, day = row
        total += 1
        if type(salon_id) is not int or salon_id < 1:
            invalid_salon += 1
        if type(day) is not int or not 1 <= day <= 7:
            invalid_day += 1
            continue
        valid += 1
        iso_day = legacy_to_iso_weekday(day)
        legacy_counts[day - 1] += 1
        iso_counts[iso_day - 1] += 1
        if type(salon_id) is int and salon_id >= 1:
            pair = (salon_id, day)
            if pair in seen:
                duplicates += 1
            seen.add(pair)
    return WeekdayRowPreview(
        total_rows=total,
        valid_day_rows=valid,
        invalid_day_rows=invalid_day,
        invalid_salon_reference_rows=invalid_salon,
        duplicate_salon_day_rows=duplicates,
        legacy_counts_saturday_first=tuple(legacy_counts),
        iso_counts_monday_first=tuple(iso_counts),
    )


SOURCE_ROOTS = ("apps", "loomera", "static/js", "templates")
SOURCE_SUFFIXES = frozenset((".py", ".js", ".html"))
SOURCE_CANDIDATE_PATTERN = re.compile(
    r"day_of_week|\.weekday\s*\(|\.isoweekday\s*\(|"
    r"\.getDay\s*\(|\bfirstDayOfWeek\b|\bweek_start\b|"
    r"day-\{\{|day-\$\{"
)


def discover_weekday_sources(base_dir: Path) -> tuple[tuple[str, int], ...]:
    """Locate weekday-related runtime source paths; do not read DB records.

    Results are candidates for human semantic review, NOT proof that a file
    operates on persisted data. Avoid tests/migrations and generated outputs.
    Paths and token counts only; no source text or user data are returned.
    """
    found: list[tuple[str, int]] = []
    for root_name in SOURCE_ROOTS:
        source_root = base_dir / root_name
        if not source_root.is_dir():
            continue
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(base_dir)
            if (
                "migrations" in relative.parts
                or "__pycache__" in relative.parts
                or "tests" in relative.parts
                or path.name.startswith("test_")
            ):
                continue
            source = path.read_text(encoding="utf-8")
            count = len(SOURCE_CANDIDATE_PATTERN.findall(source))
            if count:
                found.append((relative.as_posix(), count))
    return tuple(sorted(found))
