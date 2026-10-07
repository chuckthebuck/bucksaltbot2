"""Parse, query, render, preview, and publish the Four Awards records table.

Record identity checks operate on parsed, normalized cells rather than raw
substring matches.  Rendering uses an in-memory SQLite model for deterministic
ordering and per-user ordinals, while retaining table headers, unfamiliar manual
rows, the trailing row marker, and final-newline behavior.  Deduplication is a
review/service responsibility; rendering faithfully combines the records it is
given.
"""

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
    """Render one sorted record, adding a display ordinal after the first award."""
    display = record.display_user or record.user
    suffix = f" ({ordinal})" if ordinal > 1 else ""
    return (
        "|-\n"
        f"| [[User:{record.user}|{display}]]{suffix} || [[{record.article}]] || "
        f"{to_dts(record.award_date)} || {to_dts(record.creation_date)} || "
        f"{to_dts(record.dyk_date)} || {to_dts(record.ga_date)} || {to_dts(record.fa_date)}"
    )


def _four_awards_table(text: str) -> tuple[int, int] | None:
    """Return the character span of the Four Awards wikitable on a page."""
    heading = re.search(r"^==\s*Four Awards\s*==\s*$", text, re.M | re.I)
    start_search = heading.end() if heading else 0
    # When the heading is present, ignore unrelated tables earlier on the page.
    table_start = text.find("{|", start_search)
    if table_start < 0:
        return None
    table_end = text.find("|}", table_start)
    if table_end < 0:
        return None
    return table_start, table_end + 2


def _split_table_rows(table: str) -> tuple[str, list[str], bool, bool]:
    """Split a wikitable into header/row chunks plus closing-format metadata."""
    had_final_newline = table.endswith("\n")
    table_body = table.rstrip()
    if not table_body.endswith("|}"):
        return table, [], False, had_final_newline

    table_body = table_body[:-2].rstrip()
    # Some hand-edited tables keep a final empty row marker before ``|}``; retain
    # that stylistic detail without treating it as an award record.
    trailing_row_marker = bool(re.search(r"(?:^|\n)\|-\s*$", table_body))
    if trailing_row_marker:
        table_body = re.sub(r"(?:^|\n)\|-\s*$", "", table_body).rstrip()

    chunks = re.split(r"(?m)(?=^\|-\s*$)", table_body)
    header = chunks[0].rstrip()
    rows = [chunk.rstrip() for chunk in chunks[1:] if chunk.strip()]
    return header, rows, trailing_row_marker, had_final_newline


def _row_cells(row: str) -> list[str]:
    """Extract cells from supported inline or one-cell-per-line wiki rows."""
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
    """Return a link target/display pair, falling back to cleaned plain text."""
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
    # Existing tables encode repeat-award ordinals in display text.  They are
    # presentation data and will be recalculated from sorted records on render.
    display = re.sub(r"\s*\(\d+\)\s*$", "", display).strip()
    return target, display


def _record_from_row(row: str) -> FourAwardRecord | None:
    """Parse a supported row, returning ``None`` for losslessly preserved rows."""
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
    """Parse recognized records while separating rows that must remain untouched."""
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
    """Check for an exact normalized article-and-any-credited-user claim.

    Parsing first avoids false positives such as ``Example`` matching
    ``Exampleton`` or an article title matching a longer linked title.
    """
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
    """Check for an exact normalized article claim regardless of credited user.

    The service uses this broader check to suppress duplicate nomination work;
    the reviewer uses :func:`table_contains_record` for user-aware evidence.
    """
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
    """Load valid normalized records into an in-memory deterministic sort model."""
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
    # The autoincrement id is a stable final tie-breaker when all visible sort
    # fields are equal; no state survives after rendering closes the connection.
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
    """Return records sorted by normalized user, date, article, then insertion."""
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
    """Render supplied records while retaining unparsed rows and table formatting.

    Unparsed/manual rows remain before machine-rendered records.  Repeat-award
    ordinals are recalculated per normalized user after sorting.  This function
    does not deduplicate records; callers must decide which claims are admissible.
    """
    conn = _records_conn(records)
    try:
        lines = [model.header.rstrip()]
        raw_rows = [row.rstrip() for row in model.raw_rows if row.strip()]
        if raw_rows:
            lines.extend(raw_rows)

        # Count after sorting so each user's displayed ordinals are contiguous and
        # deterministic even when newly supplied records arrived out of order.
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
    """Combine parsed existing/new records and return a newline-terminated table."""
    model = parse_records_table(table)
    output = render_records_table(model, [*model.records, *records])
    return output if output.endswith("\n") else output + "\n"


def render_records_page_text(page_text: str, records: Iterable[FourAwardRecord]) -> str:
    """Replace only the Four Awards table with a rendering containing new rows."""
    span = _four_awards_table(page_text)
    if not span:
        raise RuntimeError("Could not find the Four Awards records table")
    start, end = span
    new_table = _insert_rows(page_text[start:end], [record for record in records if record])
    return page_text[:start] + new_table + page_text[end:]


def preview_records_table(records: Iterable[FourAwardRecord]) -> dict[str, object] | None:
    """Return the proposed full records-page wikitext without saving it."""
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
    """Submit a records-page update and return the number of proposed rows.

    ``WikiClient.save_text`` publishes in live mode and records a diff in dry-run
    mode.  The count therefore describes rows processed, not confirmed live edits.
    """
    records = [record for record in records if record]
    if not records or not ENABLE_RECORDS:
        return 0
    wiki = get_wiki()
    text = wiki.get_text(RECORDS_PAGE)
    wiki.save_text(RECORDS_PAGE, render_records_page_text(text, records), "Update Four Award records")
    return len(records)
