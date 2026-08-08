from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from .config import AWARD_DATE_OVERRIDE


def normalize_user(value: str | None) -> str:
    value = (value or "").replace("_", " ").strip()
    value = re.sub(r"\s*\(\d+\)\s*$", "", value)
    return re.sub(r"\s+", " ", value).casefold()


def normalize_title(value: str | None) -> str:
    value = (value or "").replace("_", " ").strip()
    value = re.sub(r"\s+", " ", value)
    return value[:1].upper() + value[1:] if value else ""


def parse_date(value: str | None) -> Optional[date]:
    if not value:
        return None
    value = value.strip()
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
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else value


def to_dts(value: str | date | None) -> str:
    if isinstance(value, str) and re.search(r"\{\{\s*dts\s*\|", value, re.I):
        return value
    parsed = parse_date(value) if isinstance(value, str) else value
    if not parsed:
        return ""
    return "{{dts|%04d|%02d|%02d}}" % (parsed.year, parsed.month, parsed.day)


def date_window(center: date | None, before_days: int, after_days: int) -> tuple[date | None, date | None]:
    if center is None:
        return None, None
    return center - timedelta(days=before_days), center + timedelta(days=after_days)


def award_date() -> str:
    return AWARD_DATE_OVERRIDE or date.today().isoformat()


def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def clean_wiki_value(value: str | None) -> str:
    value = strip_comments(value or "")
    value = re.sub(r"'''?", "", value)
    value = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\{\{\s*u(?:ser)?\s*\|\s*([^}|]+).*?\}\}", r"\1", value, flags=re.I)
    return one_line(value)


def split_users(value: str | None) -> list[str]:
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
        if part and key not in seen:
            users.append(part)
            seen.add(key)
    return users


def _is_placeholder_user(normalized: str) -> bool:
    return (
        normalized in {"username", "username(s)", "user name", "usernames"}
        or "remove if you are nominating yourself" in normalized
    )
