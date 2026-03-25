"""Live tests: full dry-run job lifecycle.

These tests create real database rows with ``dry_run=True`` and verify the
complete job pipeline end-to-end.  All rows created during a test are deleted
in teardown regardless of whether the test passes or fails.

Pipeline tests (those that wait for a Celery worker to process a job) are
skipped automatically when the worker heartbeat is absent or stale.
"""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.live

# How long to wait for a Celery worker to process a dry-run job (seconds).
_PIPELINE_TIMEOUT = 45


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cleanup(db_conn, *job_ids: int) -> None:
    """Delete test jobs and their items from the database."""
    for job_id in job_ids:
        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM rollback_job_items WHERE job_id=%s", (job_id,)
                )
                cur.execute("DELETE FROM rollback_jobs WHERE id=%s", (job_id,))
            db_conn.commit()
        except Exception:
            pass


def _require_worker(live_redis) -> None:
    """Skip the calling test if the Celery worker is not running."""
    hb = live_redis.get("rollback:worker:heartbeat")
    if hb is None:
        pytest.skip("Celery worker heartbeat absent – worker may not be running")
    age = time.time() - float(hb)
    if age > 120:
        pytest.skip(f"Worker heartbeat stale ({age:.0f}s) – worker may be down")


def _poll_until_terminal(client, job_id: int, timeout: int = _PIPELINE_TIMEOUT) -> dict:
    """Poll ``GET /api/v1/rollback/jobs/<id>`` until the job reaches a terminal
    status or *timeout* seconds elapse.  Returns the last response payload."""
    deadline = time.time() + timeout
    data: dict = {}
    while time.time() < deadline:
        time.sleep(2)
        resp = client.get(f"/api/v1/rollback/jobs/{job_id}")
        assert resp.status_code == 200, f"Unexpected status {resp.status_code}"
        data = resp.get_json()
        if data.get("status") in ("completed", "failed", "canceled"):
            return data
    return data


# ── Basic job CRUD ────────────────────────────────────────────────────────────


class TestJobCRUD:
    def test_create_dry_run_job_returns_queued(self, admin_client, db_conn):
        """``POST /api/v1/rollback/jobs`` creates a queued dry-run job."""
        client, user = admin_client
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": user,
                "dry_run": True,
                "items": [{"title": "File:Example.jpg", "user": "TestVandal"}],
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "job_id" in data
        assert data["status"] == "queued"
        _cleanup(db_conn, data["job_id"])

    def test_get_job_returns_correct_shape(self, admin_client, db_conn):
        """``GET /api/v1/rollback/jobs/<id>`` returns the full job payload."""
        client, user = admin_client
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": user,
                "dry_run": True,
                "items": [
                    {"title": "File:A.jpg", "user": "BotUser"},
                    {"title": "File:B.jpg", "user": "BotUser"},
                ],
            },
        )
        job_id = resp.get_json()["job_id"]
        try:
            resp = client.get(f"/api/v1/rollback/jobs/{job_id}")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["id"] == job_id
            assert data["dry_run"] is True
            assert data["total"] == 2
            assert isinstance(data["items"], list)
            assert len(data["items"]) == 2
        finally:
            _cleanup(db_conn, job_id)

    def test_get_job_log_format_returns_plain_text(self, admin_client, db_conn):
        """``?format=log`` returns a ``text/plain`` response."""
        client, user = admin_client
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": user,
                "dry_run": True,
                "items": [{"title": "File:LogTest.jpg", "user": "Vandal"}],
            },
        )
        job_id = resp.get_json()["job_id"]
        try:
            resp = client.get(f"/api/v1/rollback/jobs/{job_id}?format=log")
            assert resp.status_code == 200
            assert resp.content_type.startswith("text/plain")
        finally:
            _cleanup(db_conn, job_id)

    def test_cancel_queued_job(self, admin_client, db_conn):
        """``DELETE /api/v1/rollback/jobs/<id>`` cancels a queued job."""
        client, user = admin_client
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": user,
                "dry_run": True,
                "items": [{"title": "File:Cancel.jpg", "user": "TestUser"}],
            },
        )
        job_id = resp.get_json()["job_id"]
        try:
            resp = client.delete(f"/api/v1/rollback/jobs/{job_id}")
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "canceled"

            # Verify the status via GET.
            resp = client.get(f"/api/v1/rollback/jobs/{job_id}")
            assert resp.get_json()["status"] == "canceled"
        finally:
            _cleanup(db_conn, job_id)

    def test_batch_id_groups_multiple_jobs(self, admin_client, db_conn):
        """Two ``POST`` calls sharing the same ``batch_id`` are grouped."""
        client, user = admin_client
        batch_id = int(time.time() * 1000)

        resp1 = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": user,
                "dry_run": True,
                "batch_id": batch_id,
                "items": [{"title": "File:Batch1.jpg", "user": "User1"}],
            },
        )
        resp2 = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": user,
                "dry_run": True,
                "batch_id": batch_id,
                "items": [{"title": "File:Batch2.jpg", "user": "User1"}],
            },
        )

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        job1 = resp1.get_json()["job_id"]
        job2 = resp2.get_json()["job_id"]

        try:
            # Both jobs should share the same batch_id in the DB.
            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT batch_id FROM rollback_jobs WHERE id IN (%s, %s)",
                    (job1, job2),
                )
                rows = cur.fetchall()
            assert len(rows) == 2
            assert rows[0][0] == rows[1][0] == batch_id
        finally:
            _cleanup(db_conn, job1, job2)

    def test_progress_endpoint_reflects_job(self, admin_client, db_conn):
        """``GET /api/v1/rollback/jobs/progress?ids=<id>`` includes the job."""
        client, user = admin_client
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": user,
                "dry_run": True,
                "items": [{"title": "File:Progress.jpg", "user": "TestUser"}],
            },
        )
        job_id = resp.get_json()["job_id"]
        try:
            resp = client.get(f"/api/v1/rollback/jobs/progress?ids={job_id}")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "jobs" in data
        finally:
            _cleanup(db_conn, job_id)


# ── Full pipeline (requires Celery worker) ────────────────────────────────────


class TestJobPipeline:
    def test_dry_run_job_completes_with_all_items_successful(
        self, admin_client, db_conn, live_redis
    ):
        """A dry-run job with 3 items reaches ``completed`` with 0 failures."""
        _require_worker(live_redis)
        client, user = admin_client

        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": user,
                "dry_run": True,
                "items": [
                    {"title": "File:Pipeline1.jpg", "user": "TestUser"},
                    {"title": "File:Pipeline2.jpg", "user": "TestUser"},
                    {"title": "File:Pipeline3.jpg", "user": "TestUser"},
                ],
            },
        )
        assert resp.status_code == 200
        job_id = resp.get_json()["job_id"]

        try:
            result = _poll_until_terminal(client, job_id)
            assert result["status"] == "completed", (
                f"Expected 'completed', got '{result['status']}'"
            )
            assert result["completed"] == 3
            assert result["failed"] == 0
        finally:
            _cleanup(db_conn, job_id)

    def test_cancel_running_job_stops_processing(
        self, admin_client, db_conn, live_redis
    ):
        """Canceling a running job causes items to be marked ``canceled``."""
        _require_worker(live_redis)
        client, user = admin_client

        # Submit a moderately large job so there is time to cancel it.
        items = [
            {"title": f"File:CancelTest{i}.jpg", "user": "TestUser"}
            for i in range(10)
        ]
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={"requested_by": user, "dry_run": True, "items": items},
        )
        assert resp.status_code == 200
        job_id = resp.get_json()["job_id"]

        try:
            # Give the worker a moment to pick up the job before canceling.
            time.sleep(1)
            client.delete(f"/api/v1/rollback/jobs/{job_id}")

            # The final status should be either 'canceled' or 'completed'
            # (if it finished before the cancel was processed).
            result = _poll_until_terminal(client, job_id)
            assert result["status"] in ("canceled", "completed")
        finally:
            _cleanup(db_conn, job_id)

    def test_retry_failed_job_completes(self, admin_client, db_conn, live_redis):
        """``POST /api/v1/rollback/jobs/<id>/retry`` re-queues a failed job."""
        _require_worker(live_redis)
        client, user = admin_client

        # Create a job and manually force it into the failed state.
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": user,
                "dry_run": True,
                "items": [{"title": "File:Retry.jpg", "user": "TestUser"}],
            },
        )
        job_id = resp.get_json()["job_id"]

        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    "UPDATE rollback_jobs SET status='failed' WHERE id=%s", (job_id,)
                )
                cur.execute(
                    "UPDATE rollback_job_items SET status='failed' WHERE job_id=%s",
                    (job_id,),
                )
            db_conn.commit()

            resp = client.post(f"/api/v1/rollback/jobs/{job_id}/retry")
            assert resp.status_code == 200
            assert resp.get_json()["status"] == "queued"

            result = _poll_until_terminal(client, job_id)
            assert result["status"] == "completed"
        finally:
            _cleanup(db_conn, job_id)


# ── Real wiki rollback (requires LIVE_WIKI_EDITS=1) ──────────────────────────


class TestLiveRollback:
    """Tests that perform actual (non-dry-run) rollbacks on the wiki.

    These tests require ALL of the following:

    * ``LIVE_WIKI_EDITS=1`` environment variable – explicit opt-in to real edits
    * Bot OAuth credentials (``CONSUMER_TOKEN``, ``CONSUMER_SECRET``,
      ``ACCESS_TOKEN``, ``ACCESS_SECRET``)
    * A running Celery worker with the same OAuth credentials

    The ``live_wiki_edit`` fixture makes a uniquely-tagged edit to
    ``User:Chuckbot/rollbacktest`` and restores the page in teardown regardless
    of outcome, so running these tests repeatedly is safe.
    """

    def test_live_rollback_reverts_test_edit(
        self,
        admin_client,
        db_conn,
        live_redis,
        live_wiki_edit,
        bot_site,
    ):
        """A real (dry_run=False) rollback job reverts the bot's test edit on-wiki.

        Flow:
          1. ``live_wiki_edit`` makes a test edit containing a unique marker.
          2. A rollback job is submitted targeting ``(page, bot_username)``.
          3. The test polls until the job reaches a terminal status.
          4. The page content is re-read to confirm the marker is gone.
        """
        import pywikibot

        _require_worker(live_redis)

        client, user = admin_client
        page_title, bot_username, original_text, test_marker = live_wiki_edit

        # Sanity-check: the test edit is present before we start.
        page = pywikibot.Page(bot_site, page_title)
        assert test_marker in page.text, (
            "Pre-condition failed: test marker not found on page before rollback"
        )

        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "items": [{"title": page_title, "user": bot_username}],
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        job_id = resp.get_json()["job_id"]

        try:
            result = _poll_until_terminal(client, job_id, timeout=90)
            assert result["status"] == "completed", (
                f"Job {job_id} ended with status '{result['status']}'; "
                f"items: {result.get('items', [])}"
            )
            assert result["completed"] == 1
            assert result["failed"] == 0

            # Verify the rollback actually happened on-wiki.
            page = pywikibot.Page(bot_site, page_title)
            assert test_marker not in page.text, (
                "Test marker is still present on the page after the rollback job "
                "completed – the wiki edit was not actually reverted"
            )
        finally:
            _cleanup(db_conn, job_id)

    def test_no_op_rollback_treated_as_completed(
        self,
        admin_client,
        db_conn,
        live_redis,
        noop_rollback_page,
    ):
        """A rollback job that returns a no-op API error must end as completed.

        ``noop_rollback_page`` provides a page where the bot is the only author.
        Rolling back the bot on that page returns the ``onlyauthor`` MediaWiki
        API error.  Before the fix this counted as a failure; after the fix the
        job must finish with ``status=completed`` and ``failed=0``.
        """
        _require_worker(live_redis)

        client, _user = admin_client
        page_title, bot_username = noop_rollback_page

        resp = client.post(
            "/api/v1/rollback/jobs",
            json={"items": [{"title": page_title, "user": bot_username}]},
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        job_id = resp.get_json()["job_id"]

        try:
            result = _poll_until_terminal(client, job_id, timeout=90)
            assert result["status"] == "completed", (
                f"Expected 'completed' for a no-op rollback; "
                f"got '{result['status']}'; items: {result.get('items', [])}"
            )
            assert result["failed"] == 0, (
                f"No-op rollback error must not be counted as a failure; "
                f"items: {result.get('items', [])}"
            )
        finally:
            _cleanup(db_conn, job_id)
