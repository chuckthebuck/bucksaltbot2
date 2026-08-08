from __future__ import annotations

import json
import time
from typing import Any

from .models import FileChangePlanItem
from .schema import ensure_queue_tables
from .service import run_file_change, targets_from_payload


DEFAULT_CHUNK_SIZE = 100
MAX_CHUNK_SIZE = 500
TERMINAL_STATUSES = {"completed", "failed", "canceled"}


def progress_key(job_id: int) -> str:
    return f"chuck_file_changer:job:{int(job_id)}"


def _redis_client():
    from redis_state import r as redis_client

    return redis_client


def _get_conn():
    from toolsdb import get_conn

    return get_conn()


def _set_progress(job_id: int, payload: dict[str, Any], ttl: int = 86400) -> None:
    try:
        _redis_client().set(progress_key(job_id), json.dumps(payload), ex=ttl)
    except Exception:
        return


def get_progress(job_id: int) -> dict[str, Any] | None:
    try:
        raw = _redis_client().get(progress_key(job_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def _chunk_size(payload: dict[str, Any]) -> int:
    try:
        requested = int(payload.get("chunk_size") or DEFAULT_CHUNK_SIZE)
    except (TypeError, ValueError):
        requested = DEFAULT_CHUNK_SIZE
    return max(1, min(requested, MAX_CHUNK_SIZE))


def enqueue_file_change_batch(payload: dict[str, Any], *, username: str) -> dict[str, Any]:
    targets, source_url = targets_from_payload(payload)
    if not targets:
        raise ValueError("No targets found")

    chunk_size = _chunk_size(payload)
    batch_id = int(time.time() * 1000)
    job_ids: list[int] = []
    payload_json = json.dumps(payload, sort_keys=True)
    dry_run = bool(payload.get("dry_run", True))
    apply_requested = bool(payload.get("apply", False))

    with _get_conn() as conn:
        ensure_queue_tables(conn)
        with conn.cursor() as cursor:
            for index in range(0, len(targets), chunk_size):
                chunk = targets[index : index + chunk_size]
                cursor.execute(
                    """
                    INSERT INTO chuck_file_change_jobs
                    (
                        batch_id,
                        requested_by,
                        status,
                        dry_run,
                        apply_requested,
                        source_url,
                        payload_json,
                        total_items
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        batch_id,
                        username,
                        "queued",
                        1 if dry_run else 0,
                        1 if apply_requested else 0,
                        source_url,
                        payload_json,
                        len(chunk),
                    ),
                )
                job_id = int(cursor.lastrowid)
                job_ids.append(job_id)
                for target in chunk:
                    cursor.execute(
                        """
                        INSERT INTO chuck_file_change_job_items
                        (
                            job_id,
                            page_title,
                            target_user,
                            summary_hint,
                            status
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            job_id,
                            target.title,
                            target.user,
                            target.summary_hint,
                            "queued",
                        ),
                    )
        conn.commit()

    for job_id in job_ids:
        _set_progress(
            job_id,
            {
                "status": "queued",
                "total": 0,
                "completed": 0,
                "failed": 0,
            },
        )

    return {
        "batch_id": batch_id,
        "job_ids": job_ids,
        "job_id": job_ids[0],
        "run_ids": job_ids,
        "run_id": job_ids[0],
        "chunks": len(job_ids),
        "target_count": len(targets),
        "chunk_size": chunk_size,
    }


def get_file_change_job(job_id: int) -> dict[str, Any] | None:
    with _get_conn() as conn:
        ensure_queue_tables(conn)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, batch_id, requested_by, status, dry_run, apply_requested,
                       source_url, payload_json, result_json, error, total_items,
                       created_at, updated_at
                FROM chuck_file_change_jobs
                WHERE id=%s
                """,
                (int(job_id),),
            )
            row = cursor.fetchone()
            if not row:
                return None

            cursor.execute(
                """
                SELECT id, page_title, target_user, summary_hint, status, attempts,
                       changed, diff, error
                FROM chuck_file_change_job_items
                WHERE job_id=%s
                ORDER BY id ASC
                """,
                (int(job_id),),
            )
            item_rows = cursor.fetchall()

    result = json.loads(row[8] or "{}")
    progress = get_progress(int(row[0]))
    return {
        "id": int(row[0]),
        "run_id": int(row[0]),
        "batch_id": int(row[1]),
        "requested_by": row[2],
        "triggered_by": row[2],
        "status": row[3],
        "dry_run": bool(row[4]),
        "apply_requested": bool(row[5]),
        "source_url": row[6],
        "payload": json.loads(row[7] or "{}"),
        "result": result,
        "progress": progress,
        "error": row[9],
        "total_items": int(row[10] or 0),
        "created_at": str(row[11]) if row[11] is not None else None,
        "updated_at": str(row[12]) if row[12] is not None else None,
        "items": [
            {
                "id": int(item[0]),
                "title": item[1],
                "user": item[2],
                "summary_hint": item[3],
                "status": item[4],
                "attempts": int(item[5] or 0),
                "changed": bool(item[6]),
                "diff": item[7],
                "error": item[8],
            }
            for item in item_rows
        ],
    }


def list_file_change_jobs(
    *, requested_by: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Return durable queue history, optionally scoped to one requester."""
    limit = max(1, min(int(limit), 200))
    where = "WHERE requested_by=%s" if requested_by else ""
    params: tuple[Any, ...] = (requested_by, limit) if requested_by else (limit,)
    with _get_conn() as conn:
        ensure_queue_tables(conn)
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, batch_id, requested_by, status, dry_run, apply_requested,
                       source_url, error, total_items, created_at, updated_at
                FROM chuck_file_change_jobs
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                params,
            )
            rows = cursor.fetchall()

    return [
        {
            "id": int(row[0]),
            "batch_id": int(row[1]),
            "requested_by": row[2],
            "status": row[3],
            "dry_run": bool(row[4]),
            "apply_requested": bool(row[5]),
            "source_url": row[6],
            "error": row[7],
            "total_items": int(row[8] or 0),
            "created_at": str(row[9]) if row[9] is not None else None,
            "updated_at": str(row[10]) if row[10] is not None else None,
        }
        for row in rows
    ]


def _update_job_status(
    job_id: int,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with _get_conn() as conn:
        ensure_queue_tables(conn)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE chuck_file_change_jobs
                SET status=%s, result_json=%s, error=%s
                WHERE id=%s
                """,
                (
                    status,
                    json.dumps(result or {}, sort_keys=True) if result is not None else None,
                    error,
                    int(job_id),
                ),
            )
        conn.commit()


def _update_item(job_id: int, item: dict[str, Any]) -> None:
    with _get_conn() as conn:
        ensure_queue_tables(conn)
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE chuck_file_change_job_items
                SET status=%s, attempts=attempts + 1, changed=%s, diff=%s, error=%s
                WHERE job_id=%s AND page_title=%s
                """,
                (
                    item.get("status") or "error",
                    1 if item.get("changed") else 0,
                    item.get("diff") or None,
                    item.get("error") or None,
                    int(job_id),
                    item.get("title"),
                ),
            )
        conn.commit()


def _targets_payload_for_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = dict(job.get("payload") or {})
    payload["targets"] = [
        {
            "title": item["title"],
            "user": item.get("user"),
            "summary": item.get("summary_hint"),
        }
        for item in job.get("items", [])
    ]
    payload["source_url"] = job.get("source_url")
    return payload


def process_file_change_job(job_id: int) -> None:
    job = get_file_change_job(int(job_id))
    if job is None or job["status"] in TERMINAL_STATUSES:
        return

    _update_job_status(job_id, "running")
    _set_progress(
        job_id,
        {
            "status": "running",
            "total": len(job.get("items", [])),
            "completed": 0,
            "failed": 0,
        },
    )

    try:
        result = run_file_change(payload=_targets_payload_for_job(job))
        completed = 0
        failed = 0
        for item in result.get("items", []):
            _update_item(job_id, item)
            if item.get("status") == "error":
                failed += 1
            else:
                completed += 1
            _set_progress(
                job_id,
                {
                    "status": "running",
                    "total": len(job.get("items", [])),
                    "completed": completed,
                    "failed": failed,
                },
            )

        final_status = "completed"
        _update_job_status(job_id, final_status, result=result)
        _set_progress(
            job_id,
            {
                "status": final_status,
                "total": len(job.get("items", [])),
                "completed": completed,
                "failed": failed,
            },
        )
    except Exception as exc:
        _update_job_status(job_id, "failed", error=str(exc))
        _set_progress(
            job_id,
            {
                "status": "failed",
                "total": len(job.get("items", [])),
                "completed": 0,
                "failed": len(job.get("items", [])),
                "error": str(exc),
            },
        )
