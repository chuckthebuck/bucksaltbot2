"""Small MediaWiki API boundary with conservative G7 eligibility checks."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .models import Candidate, Inspection

_G7_RE = re.compile(
    r"\{\{\s*(?:sd|speedy\s*delete)\s*\|(?:(?!\}\}).)*\bG7\b",
    re.IGNORECASE | re.DOTALL,
)


def _timestamp(value: str) -> datetime:
    """Parse a MediaWiki UTC timestamp."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _revision_text(revision: dict[str, Any]) -> str:
    """Extract main-slot content across modern and legacy API shapes."""
    slots = revision.get("slots") or {}
    main = slots.get("main") or {}
    return str(main.get("content") or revision.get("content") or "")


def _same_user(left: str | None, right: str | None) -> bool:
    """Compare MediaWiki usernames with underscore and case normalization."""
    return bool(
        left
        and right
        and left.replace("_", " ").casefold() == right.replace("_", " ").casefold()
    )


class CommonsGateway:
    """Perform bounded reads and one explicitly validated delete action."""

    def __init__(self, site):
        """Wrap one authenticated Pywikibot site instance."""
        self.site = site

    def _submit(self, **params) -> dict[str, Any]:
        """Submit one MediaWiki API request through Pywikibot."""
        return self.site.simple_request(**params).submit()

    def discover(self, category_title: str, limit: int) -> list[Candidate]:
        """List file-namespace members of the configured category."""
        candidates: list[Candidate] = []
        continuation: dict[str, Any] = {}
        while len(candidates) < limit:
            data = self._submit(
                action="query",
                list="categorymembers",
                cmtitle=category_title,
                cmnamespace=6,
                cmtype="file",
                cmlimit=min(500, limit - len(candidates)),
                formatversion=2,
                **continuation,
            )
            for row in data.get("query", {}).get("categorymembers", []):
                title = str(row.get("title") or "").strip()
                if title:
                    candidates.append(Candidate(title, row.get("pageid")))
            continuation = data.get("continue") or {}
            if not continuation:
                break
        return candidates

    def _page_snapshot(self, title: str) -> dict[str, Any]:
        """Collect complete revision, upload, and usage lists for one file."""
        merged: dict[str, Any] | None = None
        continuation: dict[str, Any] = {}
        while True:
            data = self._submit(
                action="query",
                titles=title,
                prop="info|revisions|imageinfo|globalusage|imageusage",
                rvprop="ids|timestamp|user|content",
                rvslots="main",
                rvlimit="max",
                iiprop="timestamp|user",
                iilimit="max",
                gulimit="max",
                iulimit="max",
                formatversion=2,
                **continuation,
            )
            pages = data.get("query", {}).get("pages", [])
            page = pages[0] if pages else {"title": title, "missing": True}
            if merged is None:
                merged = dict(page)
            else:
                for key in ("revisions", "imageinfo", "globalusage", "imageusage"):
                    merged.setdefault(key, []).extend(page.get(key, []))
            continuation = data.get("continue") or {}
            if not continuation:
                return merged

    def _has_autopatrol(self, username: str) -> bool:
        """Check the effective right so inherited patrol/admin rights qualify."""
        data = self._submit(
            action="query",
            list="users",
            ususers=username,
            usprop="rights|groups",
            formatversion=2,
        )
        users = data.get("query", {}).get("users", [])
        return bool(users and "autopatrol" in (users[0].get("rights") or []))

    def inspect(
        self,
        candidate: Candidate,
        *,
        now: datetime,
        max_age_seconds: int,
    ) -> Inspection:
        """Evaluate every required G7 condition against one wiki snapshot."""
        page = self._page_snapshot(candidate.title)
        checks: dict[str, Any] = {
            "exists": not page.get("missing"),
            "file_namespace": int(page.get("ns", -1)) == 6,
            "not_redirect": not bool(page.get("redirect")),
        }

        def decision(
            eligible: bool,
            code: str,
            detail: str,
            *,
            uploader: str | None = None,
            requester: str | None = None,
            uploaded: datetime | None = None,
        ) -> Inspection:
            """Freeze the checks accumulated at one early-return decision."""
            return Inspection(
                candidate,
                eligible,
                code,
                detail,
                uploader,
                requester,
                uploaded,
                dict(checks),
            )

        if not checks["exists"]:
            return decision(False, "missing", "File no longer exists")
        if not checks["file_namespace"] or not checks["not_redirect"]:
            return decision(
                False, "not_file", "Category member is not a live file page"
            )

        revisions = sorted(
            page.get("revisions") or [], key=lambda row: str(row.get("timestamp") or "")
        )
        current_text = _revision_text(revisions[-1]) if revisions else ""
        checks["g7_marker_present"] = bool(_G7_RE.search(current_text))
        requester = None
        marker_was_present = False
        for revision in revisions:
            marker_present = bool(_G7_RE.search(_revision_text(revision)))
            if marker_present and not marker_was_present:
                requester = str(revision.get("user") or "").strip() or None
            marker_was_present = marker_present
        checks["requester_identified"] = bool(requester)

        imageinfo = sorted(
            page.get("imageinfo") or [], key=lambda row: str(row.get("timestamp") or "")
        )
        uploader = str(imageinfo[0].get("user") or "").strip() if imageinfo else None
        uploaded = _timestamp(imageinfo[0]["timestamp"]) if imageinfo else None
        checks["upload_history_present"] = bool(imageinfo and uploader and uploaded)
        if not checks["g7_marker_present"]:
            return decision(
                False,
                "missing_g7",
                "Current file page does not contain an SD G7 marker",
                uploader=uploader,
                requester=requester,
                uploaded=uploaded,
            )
        if not checks["requester_identified"]:
            return decision(
                False,
                "unknown_requester",
                "Could not identify the editor who added the current G7 marker",
                uploader=uploader,
                uploaded=uploaded,
            )
        if not checks["upload_history_present"]:
            return decision(
                False,
                "missing_upload_history",
                "File upload history is unavailable",
                requester=requester,
            )

        checks["requester_is_uploader"] = _same_user(requester, uploader)
        if not checks["requester_is_uploader"]:
            return decision(
                False,
                "requester_not_uploader",
                "The G7 marker was not added by the original uploader",
                uploader=uploader,
                requester=requester,
                uploaded=uploaded,
            )

        checks["all_binary_revisions_by_uploader"] = all(
            _same_user(str(row.get("user") or ""), uploader) for row in imageinfo
        )
        if not checks["all_binary_revisions_by_uploader"]:
            return decision(
                False,
                "other_uploaders",
                "Another user contributed a binary revision",
                uploader=uploader,
                requester=requester,
                uploaded=uploaded,
            )

        age_seconds = max(0, (now.astimezone(timezone.utc) - uploaded).total_seconds())
        checks["age_seconds"] = int(age_seconds)
        checks["younger_than_limit"] = age_seconds < max_age_seconds
        if not checks["younger_than_limit"]:
            return decision(
                False,
                "too_old",
                "File is not strictly younger than the configured G7 limit",
                uploader=uploader,
                requester=requester,
                uploaded=uploaded,
            )

        local_usage = page.get("imageusage") or []
        global_usage = page.get("globalusage") or []
        checks["local_usage_count"] = len(local_usage)
        checks["global_usage_count"] = len(global_usage)
        checks["unused"] = not local_usage and not global_usage
        if not checks["unused"]:
            return decision(
                False,
                "in_use",
                "File is used on a Wikimedia page",
                uploader=uploader,
                requester=requester,
                uploaded=uploaded,
            )

        checks["uploader_has_autopatrol"] = self._has_autopatrol(uploader)
        if not checks["uploader_has_autopatrol"]:
            return decision(
                False,
                "not_autopatrolled",
                "Uploader does not currently hold the autopatrol right",
                uploader=uploader,
                requester=requester,
                uploaded=uploaded,
            )

        return decision(
            True,
            "eligible",
            "All self-delete safeguards passed",
            uploader=uploader,
            requester=requester,
            uploaded=uploaded,
        )

    def delete(self, title: str, reason: str) -> dict[str, Any]:
        """Delete one freshly revalidated file using an explicit CSRF request."""
        return self._submit(
            action="delete",
            title=title,
            token=self.site.tokens["csrf"],
            reason=reason,
            watchlist="nochange",
        )
