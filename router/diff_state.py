"""Diff payload and state management for rollback jobs."""

import json
import os
import time
from datetime import datetime, timezone

from app import flask_app as app
from redis_state import r
from toolsdb import get_conn

_DIFF_PAYLOAD_TTL = 7 * 24 * 3600
_MW_DEBUG_MAX_ENTRIES = 25
_MW_DEBUG_BODY_MAX = 1200
_RESOLVING_TIMEOUT_SECONDS = int(os.getenv("RESOLVING_TIMEOUT_SECONDS", "1800"))
_ROLLBACKABLE_WINDOW_LIMIT = 500
_ACCOUNT_ROLLBACK_MAX_LIMIT = 500


def _diff_payload_key(job_id: int) -> str:
    return f"rollback:diff:payload:{job_id}"


def _diff_error_key(job_id: int) -> str:
    return f"rollback:diff:error:{job_id}"


def _store_diff_payload(job_id: int, payload: dict) -> None:
    try:
        r.set(_diff_payload_key(job_id), json.dumps(payload), ex=_DIFF_PAYLOAD_TTL)
    except Exception:
        app.logger.exception("Failed to store diff payload for job %s", job_id)


def _load_diff_payload(job_id: int) -> dict | None:
    try:
        value = r.get(_diff_payload_key(job_id))
        if not value:
            return None
        return json.loads(value)
    except Exception:
        return None


def _update_diff_payload(job_id: int, updates: dict) -> None:
    payload = _load_diff_payload(job_id)
    if not payload:
        return

    payload.update(updates)
    _store_diff_payload(job_id, payload)


def _append_mw_debug(job_id: int, entry: dict) -> None:
    payload = _load_diff_payload(job_id)
    if not payload:
        return

    history = payload.get("mw_debug")
    if not isinstance(history, list):
        history = []

    history.append(entry)
    if len(history) > _MW_DEBUG_MAX_ENTRIES:
        history = history[-_MW_DEBUG_MAX_ENTRIES:]

    payload["mw_debug"] = history
    _store_diff_payload(job_id, payload)


def _created_at_to_epoch(created_at_value) -> float | None:
    if isinstance(created_at_value, datetime):
        if created_at_value.tzinfo is None:
            return created_at_value.replace(tzinfo=timezone.utc).timestamp()
        return created_at_value.timestamp()

    if isinstance(created_at_value, str):
        try:
            parsed = datetime.strptime(created_at_value, "%Y-%m-%d %H:%M:%S")
            return parsed.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None

    return None


def _maybe_mark_stale_resolving_job_failed(
    job_id: int, status: str, created_at_value
) -> bool:
    if status != "resolving":
        return False

    created_epoch = _created_at_to_epoch(created_at_value)
    if created_epoch is None:
        return False

    age_seconds = time.time() - created_epoch
    if age_seconds < _RESOLVING_TIMEOUT_SECONDS:
        return False

    error_message = (
        f"Resolve step exceeded {_RESOLVING_TIMEOUT_SECONDS} seconds; "
        "marking failed. Retry the job to re-run resolution."
    )

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE rollback_jobs SET status=%s WHERE id=%s AND status=%s",
                ("failed", job_id, "resolving"),
            )
        conn.commit()

    _set_diff_error(job_id, error_message)
    _update_diff_payload(job_id, {"resolve_error": error_message})
    return True


def _set_diff_error(job_id: int, error_message: str | None) -> None:
    try:
        if error_message:
            r.set(_diff_error_key(job_id), error_message, ex=_DIFF_PAYLOAD_TTL)
        else:
            r.delete(_diff_error_key(job_id))
    except Exception:
        app.logger.exception("Failed to update diff error state for job %s", job_id)
