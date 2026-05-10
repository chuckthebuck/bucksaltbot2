from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from difflib import unified_diff
from typing import Optional

import requests

from .config import (
    DRY_RUN,
    EDIT_TAG_LINK,
    HTTP_USER_AGENT,
    WIKI_API_URL,
    WIKI_CODE,
    WIKI_FAMILY,
)
from .models import PageCreation


try:
    from pywikibot_env import ensure_pywikibot_env
except Exception:  # pragma: no cover - supplied by the framework at runtime
    ensure_pywikibot_env = None

try:
    import pywikibot
except Exception:  # pragma: no cover - supplied by the framework at runtime
    pywikibot = None


@dataclass
class SaveResult:
    title: str
    summary: str
    saved: bool


class WikiClient:
    def __init__(self) -> None:
        self._site = None
        self.wiki_code = WIKI_CODE
        self.wiki_family = WIKI_FAMILY

    @property
    def site(self):
        if pywikibot is None:
            raise RuntimeError("pywikibot is not available")
        if self._site is None:
            if ensure_pywikibot_env is not None:
                ensure_pywikibot_env(strict=True)
            self._site = pywikibot.Site(self.wiki_code, self.wiki_family)
            self._site.login()
        return self._site

    def configure_site(self, *, wiki_code: str | None = None, wiki_family: str | None = None) -> None:
        next_code = str(wiki_code or self.wiki_code).strip() or self.wiki_code
        next_family = str(wiki_family or self.wiki_family).strip() or self.wiki_family
        if next_code != self.wiki_code or next_family != self.wiki_family:
            self.wiki_code = next_code
            self.wiki_family = next_family
            self._site = None

    def page(self, title: str):
        return pywikibot.Page(self.site, title)

    def get_text(self, title: str) -> str:
        return self.page(title).text

    def exists(self, title: str) -> bool:
        return bool(self.page(title).exists())

    def first_revision_date(self, title: str) -> Optional[date]:
        return self.page_creation(title).date

    def latest_revision_date(self, title: str) -> Optional[date]:
        data = self._query_revisions(
            title,
            {
                "rvlimit": "1",
                "rvdir": "older",
                "rvprop": "timestamp",
            },
        )
        revisions = self._revisions_from_query(data)
        if not revisions:
            return None
        timestamp = _parse_mw_timestamp(revisions[0].get("timestamp"))
        return timestamp.date() if timestamp else None

    def page_creation(self, title: str) -> PageCreation:
        data = self._query_revisions(
            title,
            {
                "rvlimit": "1",
                "rvdir": "newer",
                "rvprop": "timestamp|user",
            },
        )
        revisions = self._revisions_from_query(data)
        if not revisions:
            return PageCreation(user=None, date=None)
        revision = revisions[0]
        timestamp = _parse_mw_timestamp(revision.get("timestamp"))
        return PageCreation(user=revision.get("user"), date=timestamp.date() if timestamp else None)

    def revision_users(self, title: str, start: date | None = None, end: date | None = None, limit: int = 500) -> set[str]:
        params = {
            "rvlimit": str(max(1, min(limit, 500))),
            "rvprop": "timestamp|user",
            "rvdir": "older",
        }
        if end is not None:
            params["rvstart"] = _mw_timestamp(datetime.combine(end, time.max, timezone.utc))
        if start is not None:
            params["rvend"] = _mw_timestamp(datetime.combine(start, time.min, timezone.utc))
        try:
            data = self._query_revisions(title, params)
        except requests.RequestException:
            return set()
        return {revision["user"] for revision in self._revisions_from_query(data) if revision.get("user")}

    def page_exists(self, title: str) -> bool:
        params = {
            "action": "query",
            "titles": title,
            "format": "json",
            "formatversion": "2",
        }
        data = requests.get(WIKI_API_URL, params=params, headers=_headers(), timeout=20).json()
        pages = data.get("query", {}).get("pages", [])
        return bool(pages and not pages[0].get("missing"))

    def _query_revisions(self, title: str, revision_params: dict[str, str]) -> dict:
        params = {
            "action": "query",
            "prop": "revisions",
            "titles": title,
            "format": "json",
            "formatversion": "2",
        }
        params.update(revision_params)
        response = requests.get(WIKI_API_URL, params=params, headers=_headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def _revisions_from_query(self, data: dict) -> list[dict]:
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return []
        return pages[0].get("revisions") or []

    def save_text(self, title: str, text: str, summary: str) -> SaveResult:
        summary = f"{summary} {EDIT_TAG_LINK}".strip()
        if DRY_RUN:
            _record_dry_run_edit(self, title, text, summary)
            return SaveResult(title=title, summary=summary, saved=False)
        page = self.page(title)
        if page.text == text:
            return SaveResult(title=title, summary=summary, saved=False)
        page.text = text
        page.save(summary=summary, bot=True)
        return SaveResult(title=title, summary=summary, saved=True)

    def publish_text(self, title: str, text: str, summary: str) -> SaveResult:
        summary = f"{summary} {EDIT_TAG_LINK}".strip()
        page = self.page(title)
        if page.text == text:
            return SaveResult(title=title, summary=summary, saved=False)
        page.text = text
        page.save(summary=summary, bot=True)
        return SaveResult(title=title, summary=summary, saved=True)


_client = WikiClient()
_dry_run_edits: list[dict[str, object]] = []


def get_wiki() -> WikiClient:
    return _client


def reset_dry_run_edits() -> None:
    _dry_run_edits.clear()


def get_dry_run_edits() -> list[dict[str, object]]:
    return [dict(edit) for edit in _dry_run_edits]


def publish_dry_run_report(title: str, text: str) -> SaveResult:
    normalized_title = str(title or "").strip()
    if not normalized_title.lower().startswith("user:"):
        raise ValueError("Dry-run report page must be in userspace")
    return _client.publish_text(normalized_title, text, "Publish Four Award dry-run report")


def configure_runtime(
    *,
    wiki_code: str | None = None,
    wiki_family: str | None = None,
    wiki_api_url: str | None = None,
    dry_run: bool | None = None,
) -> None:
    global DRY_RUN, WIKI_API_URL
    _client.configure_site(wiki_code=wiki_code, wiki_family=wiki_family)
    if wiki_api_url is not None:
        WIKI_API_URL = str(wiki_api_url).strip() or WIKI_API_URL
    if dry_run is not None:
        DRY_RUN = bool(dry_run)


def _parse_mw_timestamp(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _mw_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _headers() -> dict[str, str]:
    return {"User-Agent": HTTP_USER_AGENT}


def _record_dry_run_edit(client: WikiClient, title: str, text: str, summary: str) -> None:
    try:
        before = client.get_text(title)
    except Exception as exc:
        before = ""
        error = str(exc)
    else:
        error = None

    if before == text:
        return

    diff_lines = list(
        unified_diff(
            before.splitlines(),
            text.splitlines(),
            fromfile=title,
            tofile=title,
            lineterm="",
            n=3,
        )
    )
    preview = "\n".join(diff_lines[:80])
    if len(diff_lines) > 80:
        preview += f"\n... {len(diff_lines) - 80} more diff lines ..."

    _dry_run_edits.append(
        {
            "title": title,
            "summary": summary,
            "before_chars": len(before),
            "after_chars": len(text),
            "delta_chars": len(text) - len(before),
            "diff": preview,
            "read_error": error,
        }
    )
