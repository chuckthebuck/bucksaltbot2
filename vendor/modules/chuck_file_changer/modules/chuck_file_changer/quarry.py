from __future__ import annotations

import csv
import io
import json
import re
from typing import Any
from urllib.parse import urlparse

from .models import FileChangeTarget

TITLE_COLUMNS = (
    "title",
    "page_title",
    "file",
    "file_title",
    "image",
    "img_name",
    "log_title",
)
USER_COLUMNS = ("user", "username", "target_user", "actor_name", "rev_user_text")
SUMMARY_COLUMNS = ("summary", "comment", "rev_comment", "comment_text", "reason")


def quarry_result_url(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None

    if raw.lower().startswith(("http://", "https://")):
        parsed = urlparse(raw)
        if parsed.netloc != "quarry.wmcloud.org":
            return None
        query_match = re.match(r"^/query/(\d+)(?:/|$)", parsed.path)
        if query_match:
            return f"https://quarry.wmcloud.org/query/{query_match.group(1)}/result/latest/0/json"
        run_match = re.match(r"^/run/(\d+)(?:/|$)", parsed.path)
        if run_match:
            return f"https://quarry.wmcloud.org/run/{run_match.group(1)}/output/0/json"
        return None

    query_id = re.match(r"^(?:query:)?(\d+)$", raw, flags=re.I)
    if query_id:
        return f"https://quarry.wmcloud.org/query/{query_id.group(1)}/result/latest/0/json"

    run_id = re.match(r"^run:(\d+)$", raw, flags=re.I)
    if run_id:
        return f"https://quarry.wmcloud.org/run/{run_id.group(1)}/output/0/json"

    return None


def parse_targets_text(text: str) -> list[FileChangeTarget]:
    raw = (text or "").strip()
    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        if "\t" in raw or "," in raw.splitlines()[0]:
            return parse_delimited_targets(raw)
        return parse_manual_targets(raw)

    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return targets_from_records(payload["items"])
    if isinstance(payload, dict):
        return parse_quarry_json(payload)
    if isinstance(payload, list):
        return targets_from_records(payload)
    return []


def parse_quarry_json(payload: dict[str, Any]) -> list[FileChangeTarget]:
    headers = payload.get("headers")
    rows = payload.get("rows")
    if not isinstance(headers, list) or not isinstance(rows, list):
        return []

    records = []
    for row in rows:
        if isinstance(row, list):
            records.append({str(header): row[index] if index < len(row) else "" for index, header in enumerate(headers)})
        elif isinstance(row, dict):
            records.append(row)
    return targets_from_records(records)


def parse_delimited_targets(text: str) -> list[FileChangeTarget]:
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return targets_from_records(list(reader))


def parse_manual_targets(text: str) -> list[FileChangeTarget]:
    targets: list[FileChangeTarget] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = [part.strip() for part in stripped.split("|")]
        targets.append(
            FileChangeTarget(
                title=normalize_file_title(parts[0]),
                user=parts[1] if len(parts) > 1 and parts[1] else None,
                summary_hint=parts[2] if len(parts) > 2 and parts[2] else None,
            )
        )
    return dedupe_targets(targets)


def targets_from_records(records: list[Any]) -> list[FileChangeTarget]:
    targets: list[FileChangeTarget] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        title = _first_text(record, TITLE_COLUMNS)
        if not title:
            continue
        targets.append(
            FileChangeTarget(
                title=normalize_file_title(title),
                user=_first_text(record, USER_COLUMNS) or None,
                summary_hint=_first_text(record, SUMMARY_COLUMNS) or None,
            )
        )
    return dedupe_targets(targets)


def dedupe_targets(targets: list[FileChangeTarget]) -> list[FileChangeTarget]:
    seen: set[str] = set()
    unique: list[FileChangeTarget] = []
    for target in targets:
        key = target.title.replace("_", " ").casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(target)
    return unique


def normalize_file_title(title: str) -> str:
    cleaned = str(title or "").strip().replace("_", " ")
    if not cleaned:
        return ""
    if ":" in cleaned:
        return cleaned
    return f"File:{cleaned}"


def _first_text(record: dict[str, Any], names: tuple[str, ...]) -> str:
    lookup = {str(key).lower(): value for key, value in record.items()}
    for name in names:
        value = lookup.get(name.lower())
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
