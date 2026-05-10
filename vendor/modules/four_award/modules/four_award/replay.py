from __future__ import annotations

import argparse
import difflib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import requests

from . import actions, parser, records, replies, reviewer, service, wiki
from .config import HTTP_USER_AGENT, WIKI_API_URL
from .models import PageCreation


@dataclass
class ReplayEdit:
    title: str
    before: str
    after: str
    summary: str


@dataclass
class ReplayPage:
    before: str
    expected: str | None = None


@dataclass
class ReplayWiki:
    pages: dict[str, ReplayPage]
    existing: set[str] = field(default_factory=set)
    creation: dict[str, PageCreation] = field(default_factory=dict)
    latest_revision_dates: dict[str, date] = field(default_factory=dict)
    users_by_title: dict[str, set[str]] = field(default_factory=dict)
    edits: list[ReplayEdit] = field(default_factory=list)

    def get_text(self, title: str) -> str:
        if title not in self.pages:
            return ""
        return self.pages[title].before

    def exists(self, title: str) -> bool:
        return title in self.existing or title in self.pages

    def page_creation(self, title: str) -> PageCreation:
        return self.creation.get(title, PageCreation(user=None, date=None))

    def first_revision_date(self, title: str) -> date | None:
        return self.page_creation(title).date

    def latest_revision_date(self, title: str) -> date | None:
        return self.latest_revision_dates.get(title) or self.first_revision_date(title)

    def revision_users(self, title: str, start: date | None = None, end: date | None = None, limit: int = 500) -> set[str]:
        del start, end, limit
        return set(self.users_by_title.get(title, set()))

    def save_text(self, title: str, text: str, summary: str) -> wiki.SaveResult:
        before = self.get_text(title)
        if before != text:
            self.pages.setdefault(title, ReplayPage(before=""))
            self.pages[title].before = text
            self.edits.append(ReplayEdit(title=title, before=before, after=text, summary=summary))
        return wiki.SaveResult(title=title, summary=summary, saved=True)


class ReplayFailure(AssertionError):
    pass


def fetch_revision_text(revid: int) -> str:
    params = {
        "action": "query",
        "prop": "revisions",
        "revids": str(revid),
        "rvprop": "content",
        "rvslots": "main",
        "format": "json",
        "formatversion": "2",
    }
    response = requests.get(WIKI_API_URL, params=params, headers={"User-Agent": HTTP_USER_AGENT}, timeout=30)
    response.raise_for_status()
    data = response.json()
    pages = data.get("query", {}).get("pages", [])
    revisions = pages[0].get("revisions", []) if pages else []
    if not revisions:
        raise ValueError(f"Revision {revid} was not found")
    slots = revisions[0].get("slots", {})
    return slots.get("main", {}).get("content", "")


def _page_from_case(raw: dict[str, Any]) -> ReplayPage:
    before = raw.get("before_text")
    expected = raw.get("expected_text")
    if before is None and raw.get("before_revid"):
        before = fetch_revision_text(int(raw["before_revid"]))
    if expected is None and raw.get("expected_revid"):
        expected = fetch_revision_text(int(raw["expected_revid"]))
    if before is None:
        raise ValueError("Replay page needs before_text or before_revid")
    return ReplayPage(before=before, expected=expected)


def _parse_creation(raw: dict[str, Any]) -> dict[str, PageCreation]:
    creation: dict[str, PageCreation] = {}
    for title, value in raw.items():
        creation[title] = PageCreation(
            user=value.get("user"),
            date=date.fromisoformat(value["date"]) if value.get("date") else None,
        )
    return creation


def _parse_revision_dates(raw: dict[str, Any]) -> dict[str, date]:
    return {
        title: date.fromisoformat(value)
        for title, value in raw.items()
        if value
    }


def load_case(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_replay_wiki(case: dict[str, Any]) -> ReplayWiki:
    pages = {title: _page_from_case(raw) for title, raw in case.get("pages", {}).items()}
    existing = set(case.get("existing_pages", [])) | set(pages)
    users_by_title = {
        title: set(users)
        for title, users in case.get("revision_users", {}).items()
    }
    return ReplayWiki(
        pages=pages,
        existing=existing,
        creation=_parse_creation(case.get("page_creation", {})),
        latest_revision_dates=_parse_revision_dates(case.get("latest_revision_dates", {})),
        users_by_title=users_by_title,
    )


def install_replay_wiki(client: ReplayWiki) -> None:
    wiki._client = client
    parser.get_wiki = lambda: client
    reviewer.get_wiki = lambda: client
    actions.get_wiki = lambda: client
    records.get_wiki = lambda: client
    replies.get_wiki = lambda: client


def apply_replay_settings(case: dict[str, Any]) -> None:
    settings = case.get("settings", {})
    if "allow_automated_approval" in settings:
        reviewer.ALLOW_AUTOMATED_APPROVAL = bool(settings["allow_automated_approval"])
    if "enabled" in settings:
        service.ENABLED = bool(settings["enabled"])
    if "max_nominations_per_run" in settings:
        service.MAX_NOMINATIONS_PER_RUN = int(settings["max_nominations_per_run"])
    if "award_date" in settings:
        reviewer.award_date = lambda: settings["award_date"]


def _filtered_pages(case: dict[str, Any], client: ReplayWiki) -> Iterable[str]:
    titles = case.get("compare_pages")
    if titles:
        return titles
    return [title for title, page in client.pages.items() if page.expected is not None]


def _diff(expected: str, actual: str, title: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=f"expected/{title}",
            tofile=f"actual/{title}",
            lineterm="",
        )
    )


def run_replay_case(case: dict[str, Any]) -> dict[str, Any]:
    client = build_replay_wiki(case)
    install_replay_wiki(client)
    apply_replay_settings(case)
    result = service.run_four_award_sync(payload=case.get("payload"))

    expected_result = case.get("expected_result")
    if expected_result is not None and any(
        result.get(key) != value for key, value in expected_result.items()
    ):
        raise ReplayFailure(f"Expected result {expected_result}, got {result}")

    diffs: dict[str, str] = {}
    for title in _filtered_pages(case, client):
        page = client.pages.get(title)
        if page is None or page.expected is None:
            raise ReplayFailure(f"No expected text is configured for {title}")
        actual = page.before
        if actual != page.expected:
            diffs[title] = _diff(page.expected, actual, title)

    if diffs:
        joined = "\n\n".join(diff for diff in diffs.values() if diff)
        raise ReplayFailure(joined or "Replay output did not match expected revisions")

    return {
        "result": result,
        "edits": [{"title": edit.title, "summary": edit.summary} for edit in client.edits],
    }


def main() -> int:
    arg_parser = argparse.ArgumentParser(description="Replay Four Award bot behavior against old before/after revisions.")
    arg_parser.add_argument("case", nargs="+", help="Replay case JSON file")
    args = arg_parser.parse_args()

    for case_path in args.case:
        payload = run_replay_case(load_case(case_path))
        print(f"{case_path}: ok")
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
