"""Live tests: MySQL, Redis, and Celery worker connectivity.

These tests verify that the underlying infrastructure services are reachable
and the database schema is correctly initialised.
"""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.live


# ── MySQL ─────────────────────────────────────────────────────────────────────


class TestDatabase:
    def test_connection_is_alive(self, db_conn):
        """Executing ``SELECT 1`` proves the connection is usable."""
        with db_conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1

    def test_rollback_jobs_columns(self, db_conn):
        """``rollback_jobs`` table has all required columns."""
        with db_conn.cursor() as cur:
            cur.execute("DESCRIBE rollback_jobs")
            cols = {row[0] for row in cur.fetchall()}
        assert {
            "id",
            "requested_by",
            "status",
            "dry_run",
            "batch_id",
            "created_at",
        } <= cols

    def test_rollback_job_items_columns(self, db_conn):
        """``rollback_job_items`` table has all required columns."""
        with db_conn.cursor() as cur:
            cur.execute("DESCRIBE rollback_job_items")
            cols = {row[0] for row in cur.fetchall()}
        assert {
            "id",
            "job_id",
            "file_title",
            "target_user",
            "summary",
            "status",
            "error",
            "created_at",
        } <= cols

    def test_write_and_read_row(self, db_conn):
        """Round-trips a row through ``rollback_jobs`` to confirm write access."""
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO rollback_jobs (requested_by, status, dry_run, batch_id)"
                " VALUES (%s, %s, %s, %s)",
                ("live-test-probe", "queued", 1, int(time.time() * 1000)),
            )
        db_conn.commit()

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id, requested_by FROM rollback_jobs"
                " WHERE requested_by='live-test-probe' ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()

        assert row is not None
        inserted_id = row[0]
        assert row[1] == "live-test-probe"

        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM rollback_jobs WHERE id=%s", (inserted_id,))
        db_conn.commit()

    def test_job_items_foreign_key_relationship(self, db_conn):
        """Items can be inserted and queried by ``job_id``."""
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO rollback_jobs (requested_by, status, dry_run, batch_id)"
                " VALUES (%s, %s, %s, %s)",
                ("live-test-fk", "queued", 1, int(time.time() * 1000)),
            )
        db_conn.commit()

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM rollback_jobs"
                " WHERE requested_by='live-test-fk' ORDER BY id DESC LIMIT 1"
            )
            job_id = cur.fetchone()[0]

        try:
            with db_conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO rollback_job_items"
                    " (job_id, file_title, target_user, status) VALUES (%s,%s,%s,%s)",
                    (job_id, "File:Test.jpg", "TestUser", "queued"),
                )
            db_conn.commit()

            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT file_title, status FROM rollback_job_items WHERE job_id=%s",
                    (job_id,),
                )
                item = cur.fetchone()

            assert item is not None
            assert item[0] == "File:Test.jpg"
            assert item[1] == "queued"
        finally:
            with db_conn.cursor() as cur:
                cur.execute("DELETE FROM rollback_job_items WHERE job_id=%s", (job_id,))
                cur.execute("DELETE FROM rollback_jobs WHERE id=%s", (job_id,))
            db_conn.commit()


# ── Redis ─────────────────────────────────────────────────────────────────────


class TestRedis:
    _KEY = "live-test:probe"

    def test_ping(self, live_redis):
        """Redis answers PING."""
        assert live_redis.ping() is True

    def test_set_get_delete(self, live_redis):
        """Basic key-value round-trip."""
        live_redis.set(self._KEY, "ok", ex=30)
        try:
            assert live_redis.get(self._KEY) == "ok"
        finally:
            live_redis.delete(self._KEY)

    def test_redis_state_set_get_progress(self, live_redis):
        """``redis_state.set_progress`` / ``get_progress`` round-trip."""
        from redis_state import get_progress, set_progress

        job_id = 999_999_997  # out-of-range to avoid collisions with real jobs
        payload = {"status": "running", "total": 3, "completed": 1, "failed": 0}
        set_progress(job_id, payload, ttl=30)
        try:
            result = get_progress(job_id)
            assert result == payload
        finally:
            live_redis.delete(f"rollback:job:{job_id}")

    def test_redis_state_update_progress_increments_counter(self, live_redis):
        """``redis_state.update_progress`` increments the named counter."""
        from redis_state import get_progress, set_progress, update_progress

        job_id = 999_999_998
        set_progress(
            job_id,
            {"status": "running", "total": 2, "completed": 0, "failed": 0},
            ttl=30,
        )
        try:
            update_progress(job_id, "completed")
            result = get_progress(job_id)
            assert result["completed"] == 1
            assert result["failed"] == 0
        finally:
            live_redis.delete(f"rollback:job:{job_id}")

    def test_batch_notified_flag_round_trip(self, live_redis):
        """``mark_batch_notified`` / ``is_batch_already_notified`` work end-to-end."""
        from status_updater import is_batch_already_notified, mark_batch_notified

        batch_id = 999_999_999
        # Ensure clean state
        live_redis.delete(f"rollback:notified_batch:{batch_id}")
        try:
            assert not is_batch_already_notified(batch_id)
            mark_batch_notified(batch_id)
            assert is_batch_already_notified(batch_id)
        finally:
            live_redis.delete(f"rollback:notified_batch:{batch_id}")


# ── Celery worker ─────────────────────────────────────────────────────────────


class TestCeleryWorker:
    def test_worker_heartbeat_is_fresh(self, live_redis):
        """The Celery worker must have refreshed its heartbeat within 2 minutes.

        Skipped (not failed) when the heartbeat key is absent, since the
        worker may simply not be running in this environment.
        """
        hb = live_redis.get("rollback:worker:heartbeat")
        if hb is None:
            pytest.skip(
                "Celery worker heartbeat key absent – worker may not be running"
            )
        age = time.time() - float(hb)
        assert age < 120, (
            f"Worker heartbeat is stale ({age:.0f}s old); the worker may be down"
        )
