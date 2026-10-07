"""Normalization, date, and small wikitext helpers shared across the module.

Identity comparisons use case-folded usernames with display ordinals removed,
while output keeps the first cleaned display spelling.  Title normalization only
applies MediaWiki's first-character convention.  Date conversion intentionally
preserves unrecognized source strings in ISO-facing fields so reviewers can see
evidence the parser could not confidently reinterpret.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from .config import AWARD_DATE_OVERRIDE


def normalize_user(value: str | None) -> str:
    """Return a case-insensitive username key without record-table ordinals."""
    value = (value or "").replace("_", " ").strip()
    value = re.sub(r"\s*\(\d+\)\s*$", "", value)
    return re.sub(r"\s+", " ", value).casefold()


def normalize_title(value: str | None) -> str:
    """Normalize whitespace/underscores and uppercase only the first character."""
    value = (value or "").replace("_", " ").strip()
    value = re.sub(r"\s+", " ", value)
    return value[:1].upper() + value[1:] if value else ""


def parse_date(value: str | None) -> Optional[date]:
    """Parse supported DTS, ISO, day-month-year, or month-day-year dates."""
    if not value:
        return None
    value = value.strip()
    # Records pages conventionally use {{dts|YYYY|MM|DD}}, while nomination and
    # process pages commonly expose one of the three plain-text formats below.
    m = re.search(r"\{\{\s*dts\s*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})", value, re.I)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def to_iso(value: str | date | None) -> str:
    """Return an ISO date, preserving a non-empty unrecognized source string."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else value


def to_dts(value: str | date | None) -> str:
    """Render a date as ``{{dts}}``, preserving an existing DTS value verbatim."""
    if isinstance(value, str) and re.search(r"\{\{\s*dts\s*\|", value, re.I):
        return value
    parsed = parse_date(value) if isinstance(value, str) else value
    if not parsed:
        return ""
    return "{{dts|%04d|%02d|%02d}}" % (parsed.year, parsed.month, parsed.day)


def date_window(center: date | None, before_days: int, after_days: int) -> tuple[date | None, date | None]:
    """Return inclusive-looking date bounds around evidence, or two ``None``s."""
    if center is None:
        return None, None
    return center - timedelta(days=before_days), center + timedelta(days=after_days)


def award_date() -> str:
    """Return the configured historical override or today's local ISO date."""
    return AWARD_DATE_OVERRIDE or date.today().isoformat()


def strip_comments(text: str) -> str:
    """Remove HTML comments, including multiline bot/idempotency markers."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def one_line(text: str) -> str:
    """Collapse newlines and repeated whitespace into one trimmed line."""
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def clean_wiki_value(value: str | None) -> str:
    """Reduce common wiki markup to compact human-readable parameter text."""
    value = strip_comments(value or "")
    value = re.sub(r"'''?", "", value)
    value = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\{\{\s*u(?:ser)?\s*\|\s*([^}|]+).*?\}\}", r"\1", value, flags=re.I)
    return one_line(value)


def split_users(value: str | None) -> list[str]:
    """Split, clean, filter, and stably deduplicate credited usernames.

    Commas, semicolons, slashes, ``and``, and ampersands are accepted separators.
    Template placeholder instructions are not identities and are discarded.
    """
    cleaned = clean_wiki_value(value)
    if not cleaned:
        return []
    parts = re.split(r"\s*(?:,|;|/|\band\b|&)\s*", cleaned)
    users: list[str] = []
    seen: set[str] = set()
    for part in parts:
        part = normalize_title(part)
        key = normalize_user(part)
        if _is_placeholder_user(key):
            continue
        # Keep the first display spelling but compare with the normalized key so
        # underscores/case/record ordinals cannot create duplicate claimants.
        if part and key not in seen:
            users.append(part)
            seen.add(key)
    return users


def _is_placeholder_user(normalized: str) -> bool:
    """Return whether a normalized value is template instructional text."""
    return (
        normalized in {"username", "username(s)", "user name", "usernames"}
        or "remove if you are nominating yourself" in normalized
    )
