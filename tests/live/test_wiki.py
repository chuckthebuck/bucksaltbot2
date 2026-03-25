"""Live tests: Wikimedia Commons API reachability and pywikibot authentication.

Tests in ``TestCommonsAPI`` hit the Commons API over the network but make no
edits.  Tests in ``TestBotAuth`` require bot OAuth credentials via env vars
(``CONSUMER_TOKEN``, ``CONSUMER_SECRET``, ``ACCESS_TOKEN``, ``ACCESS_SECRET``);
they are skipped automatically when those variables are absent.
"""

from __future__ import annotations

import pytest
import requests

pytestmark = pytest.mark.live

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def _get_recent_edit_revid() -> int | None:
    """Return the revid of the most recent edit on Commons, or ``None``."""
    try:
        resp = requests.get(
            _COMMONS_API,
            params={
                "action": "query",
                "list": "recentchanges",
                "rclimit": "1",
                "rctype": "edit",
                "rcprop": "ids",
                "format": "json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        rc = resp.json().get("query", {}).get("recentchanges", [])
        return rc[0]["revid"] if rc else None
    except Exception:
        return None


# ── Commons API ───────────────────────────────────────────────────────────────


class TestCommonsAPI:
    def test_api_is_reachable(self):
        """Commons API returns a valid JSON siteinfo response."""
        resp = requests.get(
            _COMMONS_API,
            params={"action": "query", "meta": "siteinfo", "format": "json"},
            timeout=15,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "query" in data
        assert "general" in data["query"]

    def test_fetch_diff_author_returns_user_and_timestamp(self):
        """``fetch_diff_author_and_timestamp`` resolves a live revision."""
        import router

        revid = _get_recent_edit_revid()
        if revid is None:
            pytest.skip("No recent edits found on Commons")

        result = router.fetch_diff_author_and_timestamp(revid)
        assert isinstance(result, dict)
        assert result.get("user"), "Expected a non-empty user field"
        assert result.get("timestamp"), "Expected a non-empty timestamp field"

    def test_extract_oldid_from_plain_integer(self):
        """``_extract_oldid`` accepts a bare revision-ID string."""
        import router

        assert router._extract_oldid("12345") == 12345

    def test_extract_oldid_from_diff_url(self):
        """``_extract_oldid`` parses the ``oldid`` query parameter from a URL."""
        import router

        url = (
            "https://commons.wikimedia.org/w/index.php"
            "?title=File%3AExample.jpg&diff=prev&oldid=99887766"
        )
        assert router._extract_oldid(url) == 99887766

    def test_extract_oldid_raises_for_missing_value(self):
        """``_extract_oldid`` raises ``ValueError`` when ``diff`` is ``None``."""
        import router

        with pytest.raises(ValueError, match="Missing diff parameter"):
            router._extract_oldid(None)

    def test_get_user_groups_returns_list(self):
        """``get_user_groups`` returns a list for any username."""
        import router

        groups = router.get_user_groups("Chuckbot")
        assert isinstance(groups, list)

    def test_fetch_contribs_respects_limit(self):
        """``fetch_contribs_after_timestamp`` respects the ``limit`` parameter."""
        import router

        revid = _get_recent_edit_revid()
        if revid is None:
            pytest.skip("No recent edits found on Commons")

        result = router.fetch_diff_author_and_timestamp(revid)
        target_user = result["user"]
        start_ts = result["timestamp"]

        # Fetch at most 1 contribution to keep the test fast.
        contribs = router.fetch_contribs_after_timestamp(
            target_user, start_ts, limit=1
        )
        assert isinstance(contribs, list)
        assert len(contribs) <= 1


# ── Toolhub API ───────────────────────────────────────────────────────────────


class TestToolhub:
    def test_get_toolhub_maintainers_returns_set(self):
        """Toolhub returns a set of maintainer usernames for ``buckbot``."""
        from app import get_toolhub_maintainers

        maintainers = get_toolhub_maintainers()
        assert isinstance(maintainers, set)

    def test_is_maintainer_returns_bool(self):
        """``is_maintainer`` returns a ``bool`` without raising."""
        from app import is_maintainer

        result = is_maintainer("Alachuckthebuck")
        assert isinstance(result, bool)


# ── Bot OAuth ─────────────────────────────────────────────────────────────────


class TestBotAuth:
    def test_bot_is_logged_in(self, bot_site):
        """Bot account authenticates and reports a non-empty username."""
        assert bot_site.logged_in()
        assert bot_site.username()

    def test_bot_has_rollback_right(self, bot_site):
        """Bot account holds the ``rollback`` user right."""
        rights = bot_site.userinfo.get("rights", [])
        assert "rollback" in rights, (
            f"Bot is missing the rollback right; currently has: {sorted(rights)}"
        )

    def test_get_notify_list_returns_list(self, bot_site):
        """``get_notify_list`` reads the notify page without raising."""
        from status_updater import get_notify_list

        users = get_notify_list(bot_site)
        assert isinstance(users, list)

    def test_is_flagged_bot_returns_bool(self, bot_site):
        """``is_flagged_bot`` returns a ``bool`` for a well-known bot account."""
        from status_updater import is_flagged_bot

        result = is_flagged_bot(bot_site, "CommonsDelinker")
        assert isinstance(result, bool)

    def test_get_last_bot_edit_returns_string(self, bot_site):
        """``get_last_bot_edit`` returns a non-empty string."""
        from status_updater import get_last_bot_edit

        result = get_last_bot_edit(site=bot_site)
        assert isinstance(result, str)
        assert result
