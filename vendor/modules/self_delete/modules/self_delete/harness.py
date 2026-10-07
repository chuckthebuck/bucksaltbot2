"""Offline fixture harness for safe, reproducible self-delete policy tests."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Candidate
from .wiki import CommonsGateway


class _FixtureRequest:
    """Minimal Pywikibot request adapter returning one fixture response."""

    def __init__(self, response: dict[str, Any]):
        """Retain the immutable response returned by ``submit``."""
        self._response = response

    def submit(self) -> dict[str, Any]:
        """Return the fixture response."""
        return self._response


class FixtureSite:
    """Read-only MediaWiki API stand-in backed by one JSON fixture."""

    def __init__(self, fixture: dict[str, Any]):
        """Index fixture candidates and initialize deletion-attempt tracking."""
        self.fixture = fixture
        self.candidates = {
            str(item.get("title") or ""): item
            for item in fixture.get("candidates", [])
            if item.get("title")
        }
        self.delete_attempts: list[str] = []

    def simple_request(self, **params: Any) -> _FixtureRequest:
        """Implement only the read requests used by :class:`CommonsGateway`."""
        if params.get("action") == "delete":
            title = str(params.get("title") or "")
            self.delete_attempts.append(title)
            raise AssertionError("The offline dry-run harness cannot delete files")

        if params.get("list") == "categorymembers":
            members = [
                {"title": title, "pageid": item.get("page_id")}
                for title, item in self.candidates.items()
            ]
            return _FixtureRequest({"query": {"categorymembers": members}})

        if params.get("list") == "users":
            username = str(params.get("ususers") or "")
            rights_by_user = self.fixture.get("rights_by_user") or {}
            rights = rights_by_user.get(username, [])
            return _FixtureRequest(
                {"query": {"users": [{"name": username, "rights": rights}]}}
            )

        title = str(params.get("titles") or "")
        item = self.candidates.get(title)
        page = dict(item.get("page") or {}) if item else {"title": title, "missing": True}
        return _FixtureRequest({"query": {"pages": [page]}})


def load_fixture(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate one harness JSON document."""
    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Fixture root must be a JSON object")
    if not isinstance(payload.get("candidates", []), list):
        raise TypeError("Fixture candidates must be a list")
    return payload


def run_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    """Run discovery and eligibility checks without SQL, network, or writes."""
    raw_now = str(fixture.get("now") or "").strip()
    now = (
        datetime.fromisoformat(raw_now.replace("Z", "+00:00")).astimezone(timezone.utc)
        if raw_now
        else datetime.now(timezone.utc)
    )
    category = str(
        fixture.get("category_title") or "Category:Other speedy deletions"
    )
    max_age_seconds = min(int(fixture.get("max_age_seconds") or 604800), 604800)
    site = FixtureSite(fixture)
    gateway = CommonsGateway(site)
    candidates = gateway.discover(category, max(1, len(site.candidates)))
    decisions = [
        gateway.inspect(
            Candidate(candidate.title, candidate.page_id),
            now=now,
            max_age_seconds=max_age_seconds,
        ).as_dict()
        for candidate in candidates
    ]
    return {
        "mode": "dry_run",
        "category_title": category,
        "now": now.isoformat(),
        "discovered": len(decisions),
        "eligible": sum(bool(item["eligible"]) for item in decisions),
        "skipped": sum(not bool(item["eligible"]) for item in decisions),
        "delete_attempts": list(site.delete_attempts),
        "decisions": decisions,
    }


def main(argv: list[str] | None = None) -> int:
    """Print a deterministic JSON dry-run report for one fixture path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", help="Path to a Self Delete JSON fixture")
    parser.add_argument(
        "--compact", action="store_true", help="Print compact rather than indented JSON"
    )
    args = parser.parse_args(argv)
    result = run_fixture(load_fixture(args.fixture))
    print(json.dumps(result, indent=None if args.compact else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
