"""Dedicated SQL queue using the framework's Celery rollback-worker pattern."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from celery import shared_task

from .audit import SQLAuditStore
from .models import Candidate
from .wiki import CommonsGateway


def _open_conn():
    """Open the framework database through the runtime integration boundary."""
    from toolsdb import open_initialized_conn

    return open_initialized_conn()


def _bot_site():
    """Reuse the rollback worker's authenticated bot-site construction."""
    from rollback_queue import _bot_site as rollback_bot_site

    return rollback_bot_site()


def enqueue_self_delete_batch(
    *,
    settings,
    run_id: int,
    candidates: list[Candidate],
    candidate_ids: dict[str, int],
    inspections: dict[str, Any],
) -> dict[str, Any]:
    """Persist dedicated worker-sized jobs and dispatch them through Celery."""
    from .schema import init_schema

    if not candidates:
        return {"job_ids": [], "batch_id": None, "chunks": 0, "total_items": 0}
    init_schema()
    batch_id = int(time.time() * 1000)
    chunk_count = min(settings.workers, len(candidates))
    chunks = [candidates[index::chunk_count] for index in range(chunk_count)]
    job_ids: list[int] = []
    with _open_conn() as conn:
        with conn.cursor() as cursor:
            for chunk in chunks:
                cursor.execute(
                    """INSERT INTO self_delete_jobs
                       (audit_run_id, batch_id, status, dry_run, total_items)
                       VALUES (%s, %s, 'queued', %s, %s)""",
                    (run_id, batch_id, int(settings.dry_run), len(chunk)),
                )
                job_id = int(cursor.lastrowid)
                job_ids.append(job_id)
                for candidate in chunk:
                    inspection = inspections[candidate.title]
                    payload = {
                        "audit_run_id": run_id,
                        "audit_candidate_id": candidate_ids[candidate.title],
                        "page_id": candidate.page_id,
                        "max_age_seconds": settings.max_age_seconds,
                        "deletion_reason": settings.deletion_reason,
                    }
                    cursor.execute(
                        """INSERT INTO self_delete_job_items
                           (job_id, audit_candidate_id, page_id, file_title,
                            target_user, payload_json, status)
                           VALUES (%s, %s, %s, %s, %s, %s, 'queued')""",
                        (
                            job_id,
                            candidate_ids[candidate.title],
                            candidate.page_id,
                            candidate.title,
                            inspection.uploader or "",
                            json.dumps(payload, sort_keys=True),
                        ),
                    )
        conn.commit()
    for job_id in job_ids:
        process_self_delete_job.delay(job_id)
    return {
        "job_id": job_ids[0],
        "job_ids": job_ids,
        "batch_id": batch_id,
        "chunks": len(job_ids),
        "total_items": len(candidates),
        "status": "queued",
        "queue_table": "self_delete_job_items",
    }


def _fetch_job(job_id: int):
    """Return one dedicated queue job row."""
    with _open_conn() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT id, audit_run_id, status, dry_run, batch_id "
            "FROM self_delete_jobs WHERE id=%s",
            (job_id,),
        )
        return cursor.fetchone()


def _update_job_status(job_id: int, status: str) -> None:
    """Persist one dedicated queue job state."""
    with _open_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE self_delete_jobs SET status=%s WHERE id=%s", (status, job_id)
            )
        conn.commit()


def _update_item(item_id: int, status: str, error: str | None = None) -> None:
    """Persist one dedicated queue item state."""
    with _open_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE self_delete_job_items SET status=%s, error=%s WHERE id=%s",
                (status, error, item_id),
            )
        conn.commit()


def claim_next_self_delete_item(preferred_batch_id: int | None = None):
    """Atomically claim one queued item, preferring the initiating batch."""
    while True:
        with _open_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT i.id, i.job_id, i.file_title, i.payload_json
                       FROM self_delete_job_items i
                       JOIN self_delete_jobs j ON j.id=i.job_id
                       WHERE i.status='queued' AND j.status IN ('queued', 'running')
                       ORDER BY CASE WHEN j.batch_id=%s THEN 0 ELSE 1 END, i.id ASC
                       LIMIT 1""",
                    (preferred_batch_id,),
                )
                item = cursor.fetchone()
                if not item:
                    return None
                cursor.execute(
                    """UPDATE self_delete_job_items
                       SET status='running', error=NULL, attempts=attempts+1
                       WHERE id=%s AND status='queued'""",
                    (item[0],),
                )
                if cursor.rowcount == 1:
                    conn.commit()
                    return item
            conn.commit()


def _derive_job_status(job_id: int) -> tuple[str, dict[str, int]]:
    """Derive a job's aggregate status from its durable item rows."""
    with _open_conn() as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT status, COUNT(*) FROM self_delete_job_items "
            "WHERE job_id=%s GROUP BY status",
            (job_id,),
        )
        counts = {str(status): int(count) for status, count in cursor.fetchall()}
    if counts.get("failed", 0):
        return "failed", counts
    if counts.get("queued", 0) or counts.get("running", 0):
        return "running", counts
    if counts.get("canceled", 0):
        return "canceled", counts
    return "completed", counts


def _reconcile_job(job_id: int) -> tuple[str, dict[str, int]]:
    """Derive and persist one job's current aggregate state."""
    status, counts = _derive_job_status(job_id)
    _update_job_status(job_id, status)
    return status, counts


def process_queued_self_delete(
    *, site, title: str, payload_json: str | None, dry_run: bool
) -> str:
    """Freshly validate and possibly delete one dedicated queue item."""
    try:
        payload = json.loads(payload_json or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Invalid self-delete queue payload") from exc
    required = ("audit_run_id", "audit_candidate_id", "max_age_seconds")
    if any(payload.get(key) is None for key in required):
        raise RuntimeError("Incomplete self-delete queue payload")
    run_id = int(payload["audit_run_id"])
    candidate_id = int(payload["audit_candidate_id"])
    candidate = Candidate(title=title, page_id=payload.get("page_id"))
    audit = SQLAuditStore(connection_factory=_open_conn)
    audit.event(
        run_id,
        candidate_id,
        "info",
        "queue_worker_started",
        "Dedicated queue worker claimed self-delete item",
        {"dry_run": bool(dry_run)},
    )
    try:
        gateway = CommonsGateway(site)
        inspection = gateway.inspect(
            candidate,
            now=datetime.now(timezone.utc),
            max_age_seconds=int(payload["max_age_seconds"]),
        )
        audit.inspection(run_id, candidate_id, inspection, phase="queue_predelete")
        if not inspection.eligible:
            detail = f"Skipped after queue recheck: {inspection.reason_detail}"
            audit.set_candidate_status(
                run_id,
                candidate_id,
                "skipped",
                f"queue_recheck_{inspection.reason_code}",
                detail,
            )
            audit.refresh_run(run_id)
            return detail
        if dry_run:
            detail = "Eligible; deletion suppressed by self-delete queue dry-run mode"
            audit.set_candidate_status(
                run_id, candidate_id, "dry_run", "dry_run", detail
            )
            audit.refresh_run(run_id)
            return detail
        reason = str(payload.get("deletion_reason") or "G7 self-delete")
        audit.event(
            run_id,
            candidate_id,
            "info",
            "delete_started",
            "Self-delete worker submitting MediaWiki delete request",
            {"reason": reason},
        )
        response = gateway.delete(title, reason)
        if not (response.get("delete") or {}):
            raise RuntimeError("MediaWiki delete response did not confirm deletion")
        detail = "MediaWiki confirmed deletion through self-delete queue"
        audit.set_candidate_status(run_id, candidate_id, "deleted", "deleted", detail)
        audit.refresh_run(run_id)
        return detail
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        audit.set_candidate_status(
            run_id, candidate_id, "failed", "queue_worker_error", detail
        )
        audit.refresh_run(run_id)
        raise


@shared_task(name="self_delete.process_job", ignore_result=True)
def process_self_delete_job(job_id: int) -> None:
    """Drain dedicated items with rollback-style atomic shared claims."""
    from .schema import init_schema

    init_schema()
    job = _fetch_job(job_id)
    if not job or str(job[2]) == "canceled":
        return
    batch_id = job[4]
    _update_job_status(job_id, "running")
    site = None
    while True:
        claimed = claim_next_self_delete_item(preferred_batch_id=batch_id)
        if not claimed:
            break
        item_id, claimed_job_id, title, payload_json = claimed
        owner = _fetch_job(int(claimed_job_id))
        if not owner:
            _update_item(int(item_id), "failed", "Missing self_delete_jobs row")
            continue
        if str(owner[2]) == "canceled":
            _update_item(int(item_id), "canceled", "Canceled")
            _reconcile_job(int(claimed_job_id))
            continue
        try:
            if site is None:
                site = _bot_site()
            detail = process_queued_self_delete(
                site=site,
                title=str(title),
                payload_json=payload_json,
                dry_run=bool(owner[3]),
            )
            _update_item(int(item_id), "completed", detail)
        except Exception as exc:  # noqa: BLE001 - isolate per-item failures
            detail = str(exc).strip() or exc.__class__.__name__
            _update_item(int(item_id), "failed", detail)
        _reconcile_job(int(claimed_job_id))
    _reconcile_job(job_id)
