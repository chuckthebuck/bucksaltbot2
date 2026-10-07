"""Durable SQL audit storage for every self-delete decision and action."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any


def _json(value: Any) -> str:
    """Serialize audit context deterministically and tolerate rich values."""
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


class SQLAuditStore:
    """Write append-heavy audit events through the framework ToolsDB factory."""

    def __init__(self, connection_factory: Callable[[], Any] | None = None):
        """Initialize schema once and retain a cheap connection factory."""
        if connection_factory is None:
            from toolsdb import open_initialized_conn

            from .schema import init_schema

            # Initialize once per cron process, then keep each verbose event
            # transaction cheap and independent for concurrent workers.
            init_schema()
            connection_factory = open_initialized_conn
        self._connection_factory = connection_factory

    def create_run(self, *, framework_run_id: int | None, settings) -> int:
        """Create and return the module-specific run identifier."""
        with self._connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO self_delete_runs (
                        framework_run_id, category_title, dry_run,
                        max_age_seconds, worker_count, status, config_json
                    ) VALUES (%s, %s, %s, %s, %s, 'running', %s)
                    """,
                    (
                        framework_run_id,
                        settings.category_title,
                        int(settings.dry_run),
                        settings.max_age_seconds,
                        settings.workers,
                        _json(settings.as_dict()),
                    ),
                )
                run_id = int(cursor.lastrowid)
            conn.commit()
        return run_id

    def add_candidate(self, run_id: int, candidate) -> int:
        """Persist discovery before any network-heavy checks begin."""
        with self._connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO self_delete_candidates (run_id, page_id, file_title)
                    VALUES (%s, %s, %s)
                    """,
                    (run_id, candidate.page_id, candidate.title),
                )
                candidate_id = int(cursor.lastrowid)
            conn.commit()
        self.event(
            run_id,
            candidate_id,
            "info",
            "candidate_discovered",
            "File discovered in configured category",
            {"title": candidate.title, "page_id": candidate.page_id},
        )
        return candidate_id

    def event(
        self,
        run_id: int,
        candidate_id: int | None,
        level: str,
        event_type: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Append one structured event, including the current worker name."""
        with self._connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO self_delete_events (
                        run_id, candidate_id, level, event_type, message,
                        context_json, worker_name
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        candidate_id,
                        level,
                        event_type,
                        message,
                        _json(context or {}),
                        threading.current_thread().name,
                    ),
                )
            conn.commit()

    def inspection(
        self,
        run_id: int,
        candidate_id: int,
        inspection,
        *,
        phase: str,
    ) -> None:
        """Store the full snapshot and emit one event per individual check."""
        status = "eligible" if inspection.eligible else "skipped"
        with self._connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE self_delete_candidates
                    SET uploader=%s, requester=%s, upload_timestamp=%s,
                        status=%s, reason_code=%s, reason_detail=%s, checks_json=%s
                    WHERE id=%s AND run_id=%s
                    """,
                    (
                        inspection.uploader,
                        inspection.requester,
                        (
                            inspection.upload_timestamp.isoformat()
                            if inspection.upload_timestamp
                            else None
                        ),
                        status,
                        inspection.reason_code,
                        inspection.reason_detail,
                        _json(inspection.checks),
                        candidate_id,
                        run_id,
                    ),
                )
            conn.commit()

        for check_name, check_value in inspection.checks.items():
            self.event(
                run_id,
                candidate_id,
                "info",
                f"{phase}_check",
                f"{check_name}={check_value!r}",
                {"check": check_name, "value": check_value, "phase": phase},
            )
        self.event(
            run_id,
            candidate_id,
            "info" if inspection.eligible else "warning",
            f"{phase}_decision",
            inspection.reason_detail,
            inspection.as_dict(),
        )

    def set_candidate_status(
        self,
        run_id: int,
        candidate_id: int,
        status: str,
        reason_code: str,
        detail: str,
    ) -> None:
        """Persist a terminal candidate state and matching event."""
        with self._connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE self_delete_candidates
                    SET status=%s, reason_code=%s, reason_detail=%s
                    WHERE id=%s AND run_id=%s
                    """,
                    (status, reason_code, detail, candidate_id, run_id),
                )
            conn.commit()
        self.event(
            run_id,
            candidate_id,
            "error" if status == "failed" else "info",
            f"candidate_{status}",
            detail,
            {"reason_code": reason_code},
        )

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        discovered: int,
        eligible: int,
        deleted: int,
        skipped: int,
        failed: int,
        error: str | None = None,
    ) -> None:
        """Finalize aggregate counts even when the run raises."""
        with self._connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE self_delete_runs
                    SET status=%s, discovered_count=%s, eligible_count=%s,
                        deleted_count=%s, skipped_count=%s, failed_count=%s,
                        error=%s, finished_at=CURRENT_TIMESTAMP
                    WHERE id=%s
                    """,
                    (
                        status,
                        discovered,
                        eligible,
                        deleted,
                        skipped,
                        failed,
                        error,
                        run_id,
                    ),
                )
            conn.commit()

    def mark_run_queued(
        self,
        run_id: int,
        *,
        discovered: int,
        eligible: int,
        skipped: int,
        failed: int,
        queue_result: dict[str, Any],
    ) -> None:
        """Record the handoff from cron discovery to shared Celery workers."""
        with self._connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE self_delete_runs
                    SET status='queued', discovered_count=%s, eligible_count=%s,
                        skipped_count=%s, failed_count=%s, error=NULL,
                        finished_at=NULL
                    WHERE id=%s
                    """,
                    (discovered, eligible, skipped, failed, run_id),
                )
                cursor.execute(
                    """
                    UPDATE self_delete_candidates
                    SET status='queued', reason_code='queued',
                        reason_detail='Queued for fresh worker validation'
                    WHERE run_id=%s AND status='eligible'
                    """,
                    (run_id,),
                )
            conn.commit()
        self.event(
            run_id,
            None,
            "info",
            "self_delete_queue_handoff",
            "Delete and failed-verification route actions handed to the dedicated queue",
            queue_result,
        )

    def refresh_run(self, run_id: int) -> dict[str, Any]:
        """Recompute aggregate run state after one queued item finishes."""
        counts: dict[str, int] = {}
        with self._connection_factory() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, COUNT(*)
                    FROM self_delete_candidates
                    WHERE run_id=%s
                    GROUP BY status
                    """,
                    (run_id,),
                )
                counts = {
                    str(status): int(count) for status, count in cursor.fetchall()
                }
                pending = sum(
                    counts.get(name, 0) for name in ("discovered", "eligible", "queued")
                )
                status = (
                    "queued"
                    if pending
                    else "failed"
                    if counts.get("failed", 0)
                    else "completed"
                )
                cursor.execute(
                    """
                    UPDATE self_delete_runs
                    SET status=%s,
                        deleted_count=%s,
                        skipped_count=%s,
                        failed_count=%s,
                        finished_at=CASE WHEN %s=0 THEN CURRENT_TIMESTAMP ELSE NULL END
                    WHERE id=%s
                    """,
                    (
                        status,
                        counts.get("deleted", 0),
                        counts.get("skipped", 0) + counts.get("rerouted", 0),
                        counts.get("failed", 0),
                        pending,
                        run_id,
                    ),
                )
            conn.commit()
        return {"status": status, "pending": pending, "counts": counts}
