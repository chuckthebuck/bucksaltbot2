"""Live tests: HTTP API endpoint smoke tests.

``TestPublicEndpoints`` covers routes accessible without authentication.
``TestAuthRequired`` asserts that every protected route returns 401 for an
anonymous visitor.
``TestAuthenticatedEndpoints`` injects a maintainer session and checks that
the routes return the expected HTTP status codes and response shapes.
"""

from __future__ import annotations

import os
import requests
import pytest

pytestmark = pytest.mark.live

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def _rollbacktest_revid() -> int | None:
    """Return a recent revision id for User:Chuckbot/rollbacktest.

    Using a dedicated test page avoids selecting anonymous/IP editors from
    global recent changes.
    """
    try:
        resp = requests.get(
            _COMMONS_API,
            params={
                "action": "query",
                "prop": "revisions",
                "titles": "User:Chuckbot/rollbacktest",
                "rvlimit": "1",
                "rvprop": "ids",
                "format": "json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            revisions = page.get("revisions") or []
            if revisions and revisions[0].get("revid"):
                return int(revisions[0]["revid"])
    except Exception:
        return None

    return None


# ── Public (unauthenticated) endpoints ────────────────────────────────────────


class TestPublicEndpoints:
    def test_index_returns_200(self, live_client):
        resp = live_client.get("/")
        assert resp.status_code == 200

    def test_worker_status_returns_valid_json(self, live_client):
        resp = live_client.get("/api/v1/rollback/worker")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "status" in data
        assert data["status"] in ("online", "offline")

    def test_login_initiates_oauth_flow(self, live_client):
        """``/login`` either redirects to Wikimedia OAuth (302) or returns a
        400 when the consumer key is unconfigured in the test environment."""
        resp = live_client.get("/login")
        assert resp.status_code in (302, 400)

    def test_goto_without_tab_redirects(self, live_client):
        resp = live_client.get("/goto")
        assert resp.status_code in (200, 302)

    def test_logout_redirects(self, live_client):
        resp = live_client.get("/logout")
        assert resp.status_code in (200, 302)


# ── Auth-required endpoints return 401/403 ───────────────────────────────────


class TestAuthRequired:
    @pytest.mark.parametrize(
        "method,url,body",
        [
            ("GET", "/api/v1/rollback/jobs", None),
            ("POST", "/api/v1/rollback/jobs", {"requested_by": "x", "items": []}),
            ("GET", "/api/v1/rollback/jobs/progress?ids=1", None),
            ("POST", "/api/v1/rollback/from-diff", {"diff": "123"}),
            ("GET", "/rollback-queue/all-jobs", None),
            ("GET", "/rollback_batch", None),
            ("GET", "/rollback-from-diff", None),
        ],
    )
    def test_returns_4xx_when_unauthenticated(self, live_client, method, url, body):
        """Every protected route must reject anonymous requests."""
        if method == "GET":
            resp = live_client.get(url)
        else:
            resp = live_client.post(url, json=body)
        assert resp.status_code in (401, 403), (
            f"{method} {url} should reject anonymous access, got {resp.status_code}"
        )


# ── Authenticated endpoints ───────────────────────────────────────────────────


class TestAuthenticatedEndpoints:
    def test_list_jobs_returns_jobs_list(self, admin_client):
        client, _user = admin_client
        resp = client.get("/api/v1/rollback/jobs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "jobs" in data
        assert isinstance(data["jobs"], list)

    def test_rollback_queue_ui_returns_html(self, admin_client):
        client, _user = admin_client
        resp = client.get("/rollback-queue")
        assert resp.status_code == 200
        assert b"html" in resp.data.lower()

    def test_all_jobs_json_endpoint(self, admin_client):
        client, _user = admin_client
        resp = client.get("/rollback-queue/all-jobs?format=json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "jobs" in data
        assert isinstance(data["jobs"], list)

    def test_batch_rollback_ui_returns_html(self, admin_client):
        client, _user = admin_client
        resp = client.get("/rollback_batch")
        assert resp.status_code == 200
        assert b"html" in resp.data.lower()

    def test_rollback_from_diff_ui_returns_html(self, admin_client):
        client, _user = admin_client
        resp = client.get("/rollback-from-diff")
        assert resp.status_code == 200
        assert b"html" in resp.data.lower()

    def test_create_job_returns_400_for_empty_items(self, admin_client):
        client, user = admin_client
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={"requested_by": user, "items": []},
        )
        assert resp.status_code == 400

    def test_get_nonexistent_job_returns_404(self, admin_client):
        client, _user = admin_client
        resp = client.get("/api/v1/rollback/jobs/999999999")
        assert resp.status_code == 404

    def test_progress_endpoint_with_unknown_id_returns_empty(self, admin_client):
        client, _user = admin_client
        resp = client.get("/api/v1/rollback/jobs/progress?ids=999999999")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "jobs" in data

    def test_cancel_nonexistent_job_returns_404(self, admin_client):
        client, _user = admin_client
        resp = client.delete("/api/v1/rollback/jobs/999999999")
        assert resp.status_code == 404

    def test_retry_nonexistent_job_returns_404(self, admin_client):
        client, _user = admin_client
        resp = client.post("/api/v1/rollback/jobs/999999999/retry")
        assert resp.status_code == 404


# ── from-diff endpoint input validation ──────────────────────────────────────


class TestFromDiffInputValidation:
    def test_missing_diff_param_returns_400(self, admin_client):
        client, _user = admin_client
        resp = client.post("/api/v1/rollback/from-diff", json={})
        assert resp.status_code == 400
        assert "diff" in resp.get_json().get("detail", "").lower()

    def test_invalid_limit_type_returns_400(self, admin_client):
        client, _user = admin_client
        resp = client.post(
            "/api/v1/rollback/from-diff",
            json={"diff": "12345", "limit": "not-a-number"},
        )
        assert resp.status_code == 400

    def test_zero_limit_returns_400(self, admin_client):
        client, _user = admin_client
        resp = client.post(
            "/api/v1/rollback/from-diff",
            json={"diff": "12345", "limit": 0},
        )
        assert resp.status_code == 400

    def test_excessive_limit_returns_400(self, admin_client):
        client, _user = admin_client
        resp = client.post(
            "/api/v1/rollback/from-diff",
            json={"diff": "12345", "limit": 99999},
        )
        assert resp.status_code == 400

    def test_valid_diff_id_creates_resolving_job(self, admin_client, db_conn):
        """A valid diff ID is auto-approved in live tests and starts ``resolving``."""
        client, _user = admin_client

        revid = _rollbacktest_revid()
        if revid is None:
            pytest.skip("Could not resolve revision id for User:Chuckbot/rollbacktest")

        resp = client.post(
            "/api/v1/rollback/from-diff",
            json={
                "diff": str(revid),
                "dry_run": True,
                "summary": (
                    "LIVE TEST PROBE: validates from-diff request creation and auto-approval"
                ),
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "resolving"
        assert "job_id" in data

        # Clean up the created job record.
        job_id = data["job_id"]
        if os.environ.get("LIVE_TEST_KEEP_JOBS"):
            return

        try:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM rollback_job_items WHERE job_id=%s", (job_id,))
                cur.execute("DELETE FROM rollback_jobs WHERE id=%s", (job_id,))
            db_conn.commit()
        except Exception:
            pass
