from __future__ import annotations

import sqlite3
import re
from dataclasses import dataclass
from typing import Iterable

from .config import ENABLE_RECORDS, RECORDS_PAGE
from .models import FourAwardRecord
from .util import clean_wiki_value, normalize_title, normalize_user, to_dts, to_iso
from .wiki import get_wiki


@dataclass(frozen=True)
class RecordsTableModel:
    """Parsed records table while preserving unrecognized rows and formatting."""
    header: str
    records: list[FourAwardRecord]
    raw_rows: list[str]
    trailing_row_marker: bool
    had_final_newline: bool


def _record_row(record: FourAwardRecord, ordinal: int) -> str:
    """Render a sorted Four Award record row."""
    display = record.display_user or record.user
    suffix = f" ({ordinal})" if ordinal > 1 else ""
    return (
        "|-\n"
        f"| [[User:{record.user}|{display}]]{suffix} || [[{record.article}]] || "
        f"{to_dts(record.award_date)} || {to_dts(record.creation_date)} || "
        f"{to_dts(record.dyk_date)} || {to_dts(record.ga_date)} || {to_dts(record.fa_date)}"
    )


def _four_awards_table(text: str) -> tuple[int, int] | None:
    """Return the byte span of the Four Awards wikitable on the records page."""
    heading = re.search(r"^==\s*Four Awards\s*==\s*$", text, re.M | re.I)
    start_search = heading.end() if heading else 0
    table_start = text.find("{|", start_search)
    if table_start < 0:
        return None
    table_end = text.find("|}", table_start)
    if table_end < 0:
        return None
    return table_start, table_end + 2


def _split_table_rows(table: str) -> tuple[str, list[str], bool, bool]:
    """Split a wikitable into header, row chunks, and formatting flags."""
    had_final_newline = table.endswith("\n")
    table_body = table.rstrip()
    if not table_body.endswith("|}"):
        return table, [], False, had_final_newline

    table_body = table_body[:-2].rstrip()
    trailing_row_marker = bool(re.search(r"(?:^|\n)\|-\s*$", table_body))
    if trailing_row_marker:
        table_body = re.sub(r"(?:^|\n)\|-\s*$", "", table_body).rstrip()

    chunks = re.split(r"(?m)(?=^\|-\s*$)", table_body)
    header = chunks[0].rstrip()
    rows = [chunk.rstrip() for chunk in chunks[1:] if chunk.strip()]
    return header, rows, trailing_row_marker, had_final_newline


def _row_cells(row: str) -> list[str]:
    """Extract cells from simple one-line or line-per-cell wikitable rows."""
    lines = row.strip().splitlines()
    if lines and re.fullmatch(r"\|-\s*", lines[0]):
        lines = lines[1:]
    body = "\n".join(lines).strip()
    if body.startswith("|"):
        body = body[1:].strip()
    if "||" in body:
        return [cell.strip() for cell in body.split("||")]
    return [
        line[1:].strip()
        for line in lines
        if line.lstrip().startswith("|") and not line.lstrip().startswith("|-")
    ]


def _link_target(value: str, namespace: str | None = None) -> tuple[str, str]:
    """Return target and display text from a wiki link cell."""
    if namespace:
        pattern = rf"\[\[\s*{re.escape(namespace)}:([^|\]#]+)(?:#[^|\]]*)?(?:\|([^\]]+))?\]\]"
    else:
        pattern = r"\[\[\s*([^|\]#]+)(?:#[^|\]]*)?(?:\|([^\]]+))?\]\]"
    match = re.search(pattern, value, re.I)
    if not match:
        cleaned = clean_wiki_value(value)
        return cleaned, cleaned
    target = clean_wiki_value(match.group(1))
    display = clean_wiki_value(match.group(2) or target)
    display = re.sub(r"\s*\(\d+\)\s*$", "", display).strip()
    return target, display


def _record_from_row(row: str) -> FourAwardRecord | None:
    """Parse a table row into a record, preserving bad rows elsewhere."""
    cells = _row_cells(row)
    if len(cells) < 2:
        return None
    user, display_user = _link_target(cells[0], "User")
    article, _display_article = _link_target(cells[1])
    user = normalize_title(user)
    article = normalize_title(article)
    if not user or not article:
        return None
    return FourAwardRecord(
        user=user,
        display_user=display_user or user,
        article=article,
        award_date=to_iso(cells[2]) if len(cells) > 2 else "",
        creation_date=to_iso(cells[3]) if len(cells) > 3 else "",
        dyk_date=to_iso(cells[4]) if len(cells) > 4 else "",
        ga_date=to_iso(cells[5]) if len(cells) > 5 else "",
        fa_date=to_iso(cells[6]) if len(cells) > 6 else "",
    )


def parse_records_table(table: str) -> RecordsTableModel:
    """Parse a Four Awards wikitable into records plus raw unknown rows."""
    header, rows, trailing_row_marker, had_final_newline = _split_table_rows(table)
    records: list[FourAwardRecord] = []
    raw_rows: list[str] = []
    for row in rows:
        record = _record_from_row(row)
        if record is None:
            raw_rows.append(row)
        else:
            records.append(record)
    return RecordsTableModel(
        header=header,
        records=records,
        raw_rows=raw_rows,
        trailing_row_marker=trailing_row_marker,
        had_final_newline=had_final_newline,
    )


def table_contains_record(table: str, article: str, users: Iterable[str]) -> bool:
    """Return whether a table already records an article for any credited user."""
    model = parse_records_table(table)
    wanted_article = normalize_title(article).casefold()
    wanted_users = {normalize_user(user) for user in users if normalize_user(user)}
    if not wanted_article or not wanted_users:
        return False
    return any(
        normalize_title(record.article).casefold() == wanted_article
        and normalize_user(record.user) in wanted_users
        for record in model.records
    )


def table_contains_article(table: str, article: str) -> bool:
    """Return whether a table already records an article for any user."""
    model = parse_records_table(table)
    wanted_article = normalize_title(article).casefold()
    if not wanted_article:
        return False
    return any(
        normalize_title(record.article).casefold() == wanted_article
        for record in model.records
    )


def page_text_contains_record(page_text: str, article: str, users: Iterable[str]) -> bool:
    """Return whether the records page text contains a matching Four Award row."""
    span = _four_awards_table(page_text)
    if not span:
        return False
    start, end = span
    return table_contains_record(page_text[start:end], article, users)


def page_text_contains_article(page_text: str, article: str) -> bool:
    """Return whether the records page text contains the article in any row."""
    span = _four_awards_table(page_text)
    if not span:
        return False
    start, end = span
    return table_contains_article(page_text[start:end], article)


def _records_conn(records: Iterable[FourAwardRecord]) -> sqlite3.Connection:
    """Load records into SQLite so sorting stays explicit and deterministic."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE four_award_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_user TEXT NOT NULL,
            user TEXT NOT NULL,
            display_user TEXT,
            article TEXT NOT NULL,
            award_date TEXT,
            creation_date TEXT,
            dyk_date TEXT,
            ga_date TEXT,
            fa_date TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO four_award_records
        (normalized_user, user, display_user, article, award_date, creation_date,
         dyk_date, ga_date, fa_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                normalize_user(record.user),
                normalize_title(record.user),
                record.display_user or normalize_title(record.user),
                normalize_title(record.article),
                to_iso(record.award_date),
                to_iso(record.creation_date),
                to_iso(record.dyk_date),
                to_iso(record.ga_date),
                to_iso(record.fa_date),
            )
            for record in records
            if record and record.user and record.article
        ],
    )
    return conn


def _sorted_records(conn: sqlite3.Connection) -> list[FourAwardRecord]:
    """Return records sorted by user, award date, article, and insertion order."""
    rows = conn.execute(
        """
        SELECT user, display_user, article, award_date, creation_date,
               dyk_date, ga_date, fa_date
        FROM four_award_records
        ORDER BY normalized_user, award_date, article, id
        """
    ).fetchall()
    return [
        FourAwardRecord(
            user=row[0],
            display_user=row[1],
            article=row[2],
            award_date=row[3],
            creation_date=row[4],
            dyk_date=row[5],
            ga_date=row[6],
            fa_date=row[7],
        )
        for row in rows
    ]


def render_records_table(model: RecordsTableModel, records: Iterable[FourAwardRecord]) -> str:
    """Render a records table while preserving header and unknown existing rows."""
    conn = _records_conn(records)
    try:
        lines = [model.header.rstrip()]
        raw_rows = [row.rstrip() for row in model.raw_rows if row.strip()]
        if raw_rows:
            lines.extend(raw_rows)

        counts: dict[str, int] = {}
        for record in _sorted_records(conn):
            key = normalize_user(record.user)
            counts[key] = counts.get(key, 0) + 1
            lines.append(_record_row(record, counts[key]))

        if model.trailing_row_marker:
            lines.append("|-")
        lines.append("|}")
        output = "\n".join(lines) + "\n"
        if not model.had_final_newline:
            output = output.rstrip("\n")
        return output
    finally:
        conn.close()


def _insert_rows(table: str, records: list[FourAwardRecord]) -> str:
    """Insert records into an existing table and keep final-newline behavior sane."""
    model = parse_records_table(table)
    output = render_records_table(model, [*model.records, *records])
    return output if output.endswith("\n") else output + "\n"


def render_records_page_text(page_text: str, records: Iterable[FourAwardRecord]) -> str:
    """Return records page text with new Four Award records inserted."""
    span = _four_awards_table(page_text)
    if not span:
        raise RuntimeError("Could not find the Four Awards records table")
    start, end = span
    new_table = _insert_rows(page_text[start:end], [record for record in records if record])
    return page_text[:start] + new_table + page_text[end:]


def preview_records_table(records: Iterable[FourAwardRecord]) -> dict[str, object] | None:
    """Return a dry-run preview of the records page update."""
    records = [record for record in records if record]
    if not records or not ENABLE_RECORDS:
        return None
    text = get_wiki().get_text(RECORDS_PAGE)
    return {
        "title": RECORDS_PAGE,
        "record_count": len(records),
        "wikitext": render_records_page_text(text, records),
    }


def sync_records_table(records: Iterable[FourAwardRecord]) -> int:
    """Persist new Four Award records to the configured records page."""
    records = [record for record in records if record]
    if not records or not ENABLE_RECORDS:
        return 0
    wiki = get_wiki()
    text = wiki.get_text(RECORDS_PAGE)
    wiki.save_text(RECORDS_PAGE, render_records_page_text(text, records), "Update Four Award records")
    return len(records)
