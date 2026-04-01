"""Job creation and resolution logic for rollback requests."""

import time

from app import flask_app as app, MAX_JOB_ITEMS
from rollback_queue import (
    process_rollback_job,
)
from toolsdb import get_conn
import status_updater

from router.authz import _effective_runtime_authz_config  # noqa: F401
from router.diff_state import (
    _load_diff_payload,
    _store_diff_payload,
    _update_diff_payload,
    _append_mw_debug,
    _set_diff_error,
    _ACCOUNT_ROLLBACK_MAX_LIMIT,
    _ROLLBACKABLE_WINDOW_LIMIT,
)
from router.wiki_api import (
    _extract_oldid,
    _normalize_target_user_input,
    fetch_diff_author_and_timestamp,
    _utc_now_iso,
    fetch_rollbackable_window_end_timestamp,
    fetch_recent_rollbackable_contribs,
    iter_contribs_after_timestamp,
    fetch_contribs_after_timestamp,
)

_REQUEST_TYPE_QUEUE = "queue"
_REQUEST_TYPE_BATCH = "batch"
_REQUEST_TYPE_DIFF = "diff"

_REQUEST_STATUS_PENDING_APPROVAL = "pending_approval"

_APPROVAL_REQUIRED_ADMIN = "admin"
_APPROVAL_REQUIRED_MAINTAINER = "maintainer"

_ENDPOINT_BATCH = "batch"
_ENDPOINT_FROM_DIFF = "from_diff"
_ENDPOINT_FROM_ACCOUNT = "from_account"

_ALLOWED_DIFF_REQUEST_ENDPOINTS = frozenset(
    {_ENDPOINT_FROM_DIFF, _ENDPOINT_FROM_ACCOUNT}
)
_ALLOWED_REQUEST_TYPES = frozenset(
    {_REQUEST_TYPE_QUEUE, _REQUEST_TYPE_BATCH, _REQUEST_TYPE_DIFF}
)


def create_rollback_jobs_from_diff(
    diff,
    summary,
    requested_by,
    dry_run=False,
    limit=None,
):
    oldid = _extract_oldid(diff)
    diff_metadata = fetch_diff_author_and_timestamp(oldid)

    target_user = diff_metadata["user"]
    start_timestamp = diff_metadata["timestamp"]

    items = fetch_contribs_after_timestamp(
        target_user,
        start_timestamp,
        limit=limit,
    )

    if not items:
        raise ValueError("No contributions found after the provided diff timestamp")

    batch_id = int(time.time() * 1000)
    job_ids = []

    with get_conn() as conn:
        with conn.cursor() as cursor:
            for i in range(0, len(items), MAX_JOB_ITEMS):
                chunk = items[i : i + MAX_JOB_ITEMS]

                cursor.execute(
                    """
                    INSERT INTO rollback_jobs
                    (requested_by, status, dry_run, batch_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (requested_by, "queued", 1 if dry_run else 0, batch_id),
                )

                job_id = cursor.lastrowid
                job_ids.append(job_id)

                for item in chunk:
                    cursor.execute(
                        """
                        INSERT INTO rollback_job_items
                        (job_id, file_title, target_user, summary, status)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            job_id,
                            item["title"],
                            item["user"],
                            summary or None,
                            "queued",
                        ),
                    )

        conn.commit()

    for job_id in job_ids:
        process_rollback_job.delay(job_id)

    return {
        "job_id": job_ids[0],
        "job_ids": job_ids,
        "chunks": len(job_ids),
        "batch_id": batch_id,
        "total_items": len(items),
        "status": "queued",
        "resolved_user": target_user,
        "resolved_timestamp": start_timestamp,
        "oldid": oldid,
    }


def resolve_diff_rollback_job_impl(job_id: int):
    payload = _load_diff_payload(job_id)

    if not payload:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE rollback_jobs SET status=%s WHERE id=%s",
                    ("failed", job_id),
                )
            conn.commit()
        _set_diff_error(job_id, "Missing queued diff payload; resubmit the job.")
        return

    requested_by = payload.get("requested_by")
    dry_run = bool(payload.get("dry_run", False))
    summary = payload.get("summary") or ""
    diff = payload.get("diff")
    limit = payload.get("limit")
    requested_endpoint = (
        str(payload.get("requested_endpoint") or _ENDPOINT_FROM_DIFF).strip().lower()
    )
    approved_endpoint = (
        str(payload.get("approved_endpoint") or requested_endpoint).strip().lower()
    )

    if approved_endpoint not in _ALLOWED_DIFF_REQUEST_ENDPOINTS:
        approved_endpoint = _ENDPOINT_FROM_DIFF

    def _debug(event: dict) -> None:
        _append_mw_debug(job_id, event)

    try:
        oldid = None
        target_user = _normalize_target_user_input(payload.get("target_user"))
        start_timestamp = None

        query_debug_payload = {
            "requested_endpoint": requested_endpoint,
            "approved_endpoint": approved_endpoint,
        }

        if diff not in (None, ""):
            oldid = _extract_oldid(diff)
            _update_diff_payload(job_id, {"oldid": oldid})

            diff_metadata = fetch_diff_author_and_timestamp(
                oldid, debug_callback=_debug
            )
            target_user = target_user or diff_metadata["user"]
            start_timestamp = diff_metadata["timestamp"]

            query_debug_payload["oldid"] = oldid
            query_debug_payload["revision_query"] = {
                "action": "query",
                "prop": "revisions",
                "revids": str(oldid),
                "rvprop": "ids|user|timestamp",
                "format": "json",
            }

        if not target_user:
            raise ValueError("Unable to resolve target user for rollback request")

        parsed_limit = None
        if limit not in (None, ""):
            try:
                parsed_limit = int(limit)
            except (TypeError, ValueError) as exc:
                raise ValueError("limit must be an integer") from exc
            if parsed_limit <= 0:
                raise ValueError("limit must be a positive integer")

        created_job_ids = []
        total_items = 0
        pending_chunk = []

        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT batch_id FROM rollback_jobs WHERE id=%s",
                    (job_id,),
                )
                row = cursor.fetchone()

                if not row:
                    raise ValueError("Job not found")

                batch_id = row[0] or int(time.time() * 1000)

                # Clear any stale items from previous failed attempts.
                cursor.execute(
                    "DELETE FROM rollback_job_items WHERE job_id=%s", (job_id,)
                )

                def _persist_chunk(chunk_items, target_job_id):
                    for item in chunk_items:
                        cursor.execute(
                            """
                            INSERT INTO rollback_job_items
                            (job_id, file_title, target_user, summary, status)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                target_job_id,
                                item["title"],
                                item["user"],
                                summary or None,
                                "queued",
                            ),
                        )

                def _next_target_job_id():
                    if not created_job_ids:
                        cursor.execute(
                            """
                            UPDATE rollback_jobs
                            SET status=%s, dry_run=%s, requested_by=%s, batch_id=%s
                            WHERE id=%s
                            """,
                            (
                                "staging",
                                1 if dry_run else 0,
                                requested_by,
                                batch_id,
                                job_id,
                            ),
                        )
                        return job_id

                    cursor.execute(
                        """
                        INSERT INTO rollback_jobs
                        (
                            requested_by,
                            status,
                            dry_run,
                            batch_id,
                            request_type,
                            requested_endpoint,
                            approved_endpoint,
                            approval_required,
                            approved_by,
                            approved_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                        """,
                        (
                            requested_by,
                            "staging",
                            1 if dry_run else 0,
                            batch_id,
                            _REQUEST_TYPE_DIFF,
                            requested_endpoint,
                            approved_endpoint,
                            _APPROVAL_REQUIRED_MAINTAINER,
                            payload.get("approved_by"),
                        ),
                    )
                    chunk_job_id = cursor.lastrowid

                    # Keep the same diff/query context on every chunk job.
                    _store_diff_payload(
                        chunk_job_id,
                        {
                            "diff": diff,
                            "summary": summary,
                            "requested_by": requested_by,
                            "dry_run": dry_run,
                            "limit": limit,
                            "target_user": target_user,
                            "requested_endpoint": requested_endpoint,
                            "approved_endpoint": approved_endpoint,
                            "resolved_user": target_user,
                            "resolved_timestamp": start_timestamp,
                            **query_debug_payload,
                            "source_job_id": job_id,
                        },
                    )
                    return chunk_job_id

                if approved_endpoint == _ENDPOINT_FROM_ACCOUNT:
                    effective_limit = parsed_limit or _ACCOUNT_ROLLBACK_MAX_LIMIT
                    if effective_limit > _ACCOUNT_ROLLBACK_MAX_LIMIT:
                        raise ValueError(
                            f"limit must be <= {_ACCOUNT_ROLLBACK_MAX_LIMIT}"
                        )

                    query_debug_payload["contribs_query"] = {
                        "action": "query",
                        "list": "usercontribs",
                        "ucuser": target_user,
                        "uclimit": str(
                            min(_ACCOUNT_ROLLBACK_MAX_LIMIT, int(effective_limit))
                        ),
                        "ucprop": "ids|title|timestamp",
                        "ucshow": "top",
                        "ucstart": _utc_now_iso(),
                        "ucdir": "older",
                        "format": "json",
                    }

                    _update_diff_payload(
                        job_id,
                        {
                            **query_debug_payload,
                            "resolved_user": target_user,
                            "resolved_timestamp": start_timestamp,
                        },
                    )

                    account_items = fetch_recent_rollbackable_contribs(
                        target_user,
                        limit=effective_limit,
                        debug_callback=_debug,
                    )

                    for item in account_items:
                        pending_chunk.append(item)
                        total_items += 1

                        if len(pending_chunk) < MAX_JOB_ITEMS:
                            continue

                        target_job_id = _next_target_job_id()
                        _persist_chunk(pending_chunk, target_job_id)
                        created_job_ids.append(target_job_id)
                        pending_chunk = []
                else:
                    if not start_timestamp:
                        raise ValueError(
                            "Missing diff timestamp for from-diff resolution"
                        )

                    first_uclimit = (
                        str(min(500, int(parsed_limit)))
                        if parsed_limit is not None
                        else "500"
                    )

                    rollbackable_end_timestamp = (
                        fetch_rollbackable_window_end_timestamp(
                            target_user,
                            start_timestamp,
                            limit=_ROLLBACKABLE_WINDOW_LIMIT,
                            debug_callback=_debug,
                        )
                    )

                    query_debug_payload["contribs_query"] = {
                        "action": "query",
                        "list": "usercontribs",
                        "ucuser": target_user,
                        "uclimit": first_uclimit,
                        "ucprop": "ids|title|timestamp",
                        "ucshow": "top",
                        "ucstart": start_timestamp,
                        "ucend": rollbackable_end_timestamp,
                        "ucdir": "newer",
                        "format": "json",
                    }
                    query_debug_payload["rollbackable_window_limit"] = (
                        _ROLLBACKABLE_WINDOW_LIMIT
                    )
                    query_debug_payload["rollbackable_window_end_timestamp"] = (
                        rollbackable_end_timestamp
                    )

                    _update_diff_payload(
                        job_id,
                        {
                            **query_debug_payload,
                            "resolved_user": target_user,
                            "resolved_timestamp": start_timestamp,
                        },
                    )

                    for item in iter_contribs_after_timestamp(
                        target_user,
                        start_timestamp,
                        limit=parsed_limit,
                        end_timestamp=rollbackable_end_timestamp,
                        rollbackable_only=True,
                        debug_callback=_debug,
                    ):
                        pending_chunk.append(item)
                        total_items += 1

                        if len(pending_chunk) < MAX_JOB_ITEMS:
                            continue

                        target_job_id = _next_target_job_id()
                        _persist_chunk(pending_chunk, target_job_id)
                        created_job_ids.append(target_job_id)
                        pending_chunk = []

                if pending_chunk:
                    target_job_id = _next_target_job_id()
                    _persist_chunk(pending_chunk, target_job_id)
                    created_job_ids.append(target_job_id)

                if not created_job_ids:
                    raise ValueError(
                        "No rollbackable contributions found for the approved request"
                    )

                # Move all staged jobs to queued only after full list/chunks are built.
                for staged_job_id in created_job_ids:
                    cursor.execute(
                        "UPDATE rollback_jobs SET status=%s WHERE id=%s",
                        ("queued", staged_job_id),
                    )

            conn.commit()

        _set_diff_error(job_id, None)

        status_updater.update_wiki_status(
            editing="Actively editing",
            current_job=f"Processing {total_items} resolved items from {approved_endpoint}",
            details=f"Request resolved successfully into {len(created_job_ids)} job(s)",
        )

        for queued_job_id in created_job_ids:
            process_rollback_job.delay(queued_job_id)

    except Exception as e:  # noqa: BLE001
        app.logger.exception("Failed to resolve diff rollback job %s", job_id)
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE rollback_jobs SET status=%s WHERE id=%s",
                    ("failed", job_id),
                )
            conn.commit()
        _set_diff_error(job_id, str(e))
        _update_diff_payload(job_id, {"resolve_error": str(e)})
        status_updater.update_wiki_status(
            editing="Error",
            last_job=f"Failed to resolve diff for job {job_id}",
            details=str(e)[:200],
        )
