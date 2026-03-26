import os
import json
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import mwoauth
import mwoauth.flask
import requests
import logging
from celery import shared_task

import status_updater
from flask import (
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from app import BOT_ADMIN_ACCOUNTS, MAX_JOB_ITEMS, flask_app as app, is_maintainer
from redis_state import get_progress, r
from rollback_queue import process_rollback_job
from toolsdb import get_conn, get_runtime_config, upsert_runtime_config

ALLOWED_GROUPS = {"sysop", "rollbacker"}
GROUP_CACHE_TTL = 300
_group_cache = {}


def _env_user_set(env_var: str) -> set[str]:
    """Parse a comma-separated environment variable into a lower-cased set of usernames."""
    return {u.strip().lower() for u in os.getenv(env_var, "").split(",") if u.strip()}


# Comma-separated list of individual MediaWiki account names that are
# authorised to use this tool.  Intended for adding test accounts without
# granting full maintainer privileges.
# Example: EXTRA_AUTHORIZED_USERS=Alice,TestUser42
EXTRA_AUTHORIZED_USERS: set[str] = _env_user_set("EXTRA_AUTHORIZED_USERS")

# Users who may view their own jobs but cannot submit, cancel, or retry.
# Example: USERS_READ_ONLY=Viewer1,Viewer2
USERS_READ_ONLY: set[str] = _env_user_set("USERS_READ_ONLY")

# Tester accounts: above regular users, below maintainers.
# They receive access to all tools (from_diff, batch, read_all) and a separate,
# slightly higher rate limit, but no cross-user cancel/retry privileges.
# Example: USERS_TESTER=Alice,TestAccount
USERS_TESTER: set[str] = _env_user_set("USERS_TESTER")

# Non-maintainer users granted access to specific interfaces or cross-user actions.
# Example: USERS_GRANTED_FROM_DIFF=Alice,TestAccount
USERS_GRANTED_FROM_DIFF: set[str] = _env_user_set("USERS_GRANTED_FROM_DIFF")
USERS_GRANTED_VIEW_ALL: set[str] = _env_user_set("USERS_GRANTED_VIEW_ALL")
USERS_GRANTED_BATCH: set[str] = _env_user_set("USERS_GRANTED_BATCH")
USERS_GRANTED_CANCEL_ANY: set[str] = _env_user_set("USERS_GRANTED_CANCEL_ANY")
USERS_GRANTED_RETRY_ANY: set[str] = _env_user_set("USERS_GRANTED_RETRY_ANY")

# Per-user rate limit on job creation.  0 = disabled (the default).
# Maintainers are never rate-limited.  Testers use RATE_LIMIT_TESTER_JOBS_PER_HOUR
# (falls back to RATE_LIMIT_JOBS_PER_HOUR if unset).
# Example: RATE_LIMIT_JOBS_PER_HOUR=20
RATE_LIMIT_JOBS_PER_HOUR: int = int(os.getenv("RATE_LIMIT_JOBS_PER_HOUR", "0"))
# Example: RATE_LIMIT_TESTER_JOBS_PER_HOUR=50
RATE_LIMIT_TESTER_JOBS_PER_HOUR: int = int(
    os.getenv("RATE_LIMIT_TESTER_JOBS_PER_HOUR", str(RATE_LIMIT_JOBS_PER_HOUR))
)

_CONFIG_EDIT_PRIMARY_ACCOUNT = os.getenv("CONFIG_EDIT_PRIMARY_ACCOUNT", "chuckbot").strip().lower()

_USER_SET_CONFIG_KEYS = {
    "EXTRA_AUTHORIZED_USERS",
    "USERS_READ_ONLY",
    "USERS_TESTER",
    "USERS_GRANTED_FROM_DIFF",
    "USERS_GRANTED_VIEW_ALL",
    "USERS_GRANTED_BATCH",
    "USERS_GRANTED_CANCEL_ANY",
    "USERS_GRANTED_RETRY_ANY",
}

_INT_CONFIG_KEYS = {
    "RATE_LIMIT_JOBS_PER_HOUR",
    "RATE_LIMIT_TESTER_JOBS_PER_HOUR",
}

_RUNTIME_AUTHZ_ALLOWED_KEYS = sorted(_USER_SET_CONFIG_KEYS | _INT_CONFIG_KEYS)
_RUNTIME_AUTHZ_CACHE_TTL = 60
_runtime_authz_cache = None
_runtime_authz_cache_expiry = 0.0


def _parse_user_csv(raw_value: str) -> set[str]:
    return {u.strip().lower() for u in (raw_value or "").split(",") if u.strip()}


def _parse_nonnegative_int(value, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback

    if parsed < 0:
        return fallback

    return parsed


def _runtime_authz_defaults() -> dict:
    return {
        "EXTRA_AUTHORIZED_USERS": set(EXTRA_AUTHORIZED_USERS),
        "USERS_READ_ONLY": set(USERS_READ_ONLY),
        "USERS_TESTER": set(USERS_TESTER),
        "USERS_GRANTED_FROM_DIFF": set(USERS_GRANTED_FROM_DIFF),
        "USERS_GRANTED_VIEW_ALL": set(USERS_GRANTED_VIEW_ALL),
        "USERS_GRANTED_BATCH": set(USERS_GRANTED_BATCH),
        "USERS_GRANTED_CANCEL_ANY": set(USERS_GRANTED_CANCEL_ANY),
        "USERS_GRANTED_RETRY_ANY": set(USERS_GRANTED_RETRY_ANY),
        "RATE_LIMIT_JOBS_PER_HOUR": int(RATE_LIMIT_JOBS_PER_HOUR),
        "RATE_LIMIT_TESTER_JOBS_PER_HOUR": int(RATE_LIMIT_TESTER_JOBS_PER_HOUR),
    }


def _invalidate_runtime_authz_cache() -> None:
    global _runtime_authz_cache, _runtime_authz_cache_expiry
    _runtime_authz_cache = None
    _runtime_authz_cache_expiry = 0.0


def _load_runtime_authz_overrides() -> dict:
    global _runtime_authz_cache, _runtime_authz_cache_expiry

    now = time.time()
    if _runtime_authz_cache is not None and now < _runtime_authz_cache_expiry:
        return _runtime_authz_cache

    overrides = {}
    defaults = _runtime_authz_defaults()

    try:
        rows = get_runtime_config(_RUNTIME_AUTHZ_ALLOWED_KEYS)
    except Exception:
        app.logger.warning("Failed to load runtime authz config; using env defaults.")
        rows = {}

    for key, raw_value in rows.items():
        if key in _USER_SET_CONFIG_KEYS:
            overrides[key] = _parse_user_csv(raw_value)
            continue

        if key in _INT_CONFIG_KEYS:
            overrides[key] = _parse_nonnegative_int(raw_value, defaults[key])

    _runtime_authz_cache = overrides
    _runtime_authz_cache_expiry = now + _RUNTIME_AUTHZ_CACHE_TTL
    return overrides


def _effective_runtime_authz_config() -> dict:
    cfg = _runtime_authz_defaults()
    cfg.update(_load_runtime_authz_overrides())
    return cfg


def _serialize_runtime_authz_config(config: dict) -> dict:
    output = {}
    for key in _RUNTIME_AUTHZ_ALLOWED_KEYS:
        value = config.get(key)
        if key in _USER_SET_CONFIG_KEYS:
            output[key] = sorted(value or set())
        else:
            output[key] = int(value or 0)
    return output


def _normalize_user_list_input(value, key: str) -> list[str]:
    if isinstance(value, str):
        candidates = [part.strip() for part in value.replace("\n", ",").split(",")]
    elif isinstance(value, list):
        candidates = [str(part).strip() for part in value]
    else:
        raise ValueError(f"{key} must be a comma-separated string or a string list")

    normalized = []
    seen = set()
    for item in candidates:
        if not item:
            continue
        lowered = item.lower()
        if len(lowered) > 85:
            raise ValueError(f"{key} has a username longer than 85 characters")
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(lowered)

    if len(normalized) > 500:
        raise ValueError(f"{key} cannot contain more than 500 users")

    return sorted(normalized)


def _normalize_runtime_authz_updates(payload: dict) -> tuple[dict, list[str]]:
    normalized = {}
    errors = []

    for key, value in payload.items():
        if key not in _RUNTIME_AUTHZ_ALLOWED_KEYS:
            errors.append(f"Unknown config key: {key}")
            continue

        if key in _USER_SET_CONFIG_KEYS:
            try:
                normalized[key] = _normalize_user_list_input(value, key)
            except ValueError as exc:
                errors.append(str(exc))
            continue

        if key in _INT_CONFIG_KEYS:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                errors.append(f"{key} must be an integer")
                continue

            if parsed < 0:
                errors.append(f"{key} must be >= 0")
                continue

            if parsed > 100000:
                errors.append(f"{key} must be <= 100000")
                continue

            normalized[key] = parsed

    return normalized, errors


def _persist_runtime_authz_updates(updates: dict, updated_by: str) -> None:
    rows = {}
    for key, value in updates.items():
        if key in _USER_SET_CONFIG_KEYS:
            rows[key] = ",".join(value)
        else:
            rows[key] = str(value)

    upsert_runtime_config(rows, updated_by=updated_by)
    _invalidate_runtime_authz_cache()

_DIFF_PAYLOAD_TTL = 7 * 24 * 3600
_MW_DEBUG_MAX_ENTRIES = 25
_MW_DEBUG_BODY_MAX = 1200
_RESOLVING_TIMEOUT_SECONDS = int(os.getenv("RESOLVING_TIMEOUT_SECONDS", "1800"))
_ROLLBACKABLE_WINDOW_LIMIT = 500


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


def _maybe_mark_stale_resolving_job_failed(job_id: int, status: str, created_at_value) -> bool:
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


def _extract_oldid(diff_value):
    if diff_value is None:
        raise ValueError("Missing diff parameter")

    raw = str(diff_value).strip()

    if not raw:
        raise ValueError("Missing diff parameter")

    if raw.isdigit():
        return int(raw)

    parsed = urlparse(raw)
    oldid = parse_qs(parsed.query).get("oldid", [None])[0]

    if oldid and str(oldid).strip().isdigit():
        return int(str(oldid).strip())

    raise ValueError("diff must be a revision id or URL containing oldid")


def fetch_diff_author_and_timestamp(oldid, debug_callback=None):
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "revisions",
        "revids": str(oldid),
        "rvprop": "ids|user|timestamp",
        "format": "json",
    }

    started = time.perf_counter()
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if callable(debug_callback):
            debug_callback(
                {
                    "kind": "revisions",
                    "params": params,
                    "status_code": resp.status_code,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "response_snippet": resp.text[:_MW_DEBUG_BODY_MAX],
                }
            )
    except requests.RequestException as e:
        if callable(debug_callback):
            debug_callback(
                {
                    "kind": "revisions",
                    "params": params,
                    "error": f"{type(e).__name__}: {e}",
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                }
            )
        app.logger.error("Failed to fetch revision metadata for oldid %s: %s", oldid, e)
        raise ValueError(f"Failed to fetch revision metadata: {e}") from e

    pages = data.get("query", {}).get("pages", {})

    for page in pages.values():
        revisions = page.get("revisions") or []

        if revisions:
            revision = revisions[0]
            user = revision.get("user")
            timestamp = revision.get("timestamp")

            if user and timestamp:
                return {
                    "user": user,
                    "timestamp": timestamp,
                }

    raise ValueError("Revision not found for provided diff")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_rollbackable_window_end_timestamp(
    target_user,
    start_timestamp,
    limit=_ROLLBACKABLE_WINDOW_LIMIT,
    debug_callback=None,
):
    """Return timestamp of the oldest edit in the latest rollbackable window.

    We use Action API usercontribs with ucshow=top (rollbackable candidates),
    bounded by ucend=start_timestamp and uclimit<=500.
    """
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "usercontribs",
        "ucuser": target_user,
        "uclimit": str(min(_ROLLBACKABLE_WINDOW_LIMIT, int(limit))),
        "ucprop": "ids|title|timestamp",
        "ucshow": "top",
        "ucstart": _utc_now_iso(),
        "ucend": start_timestamp,
        "ucdir": "older",
        "format": "json",
    }

    started = time.perf_counter()
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if callable(debug_callback):
            debug_callback(
                {
                    "kind": "usercontribs-window",
                    "params": params,
                    "status_code": resp.status_code,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "response_snippet": resp.text[:_MW_DEBUG_BODY_MAX],
                }
            )
    except requests.RequestException as e:
        if callable(debug_callback):
            debug_callback(
                {
                    "kind": "usercontribs-window",
                    "params": params,
                    "error": f"{type(e).__name__}: {e}",
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                }
            )
        raise ValueError(f"Failed to fetch rollbackable contribution window: {e}") from e

    contribs = data.get("query", {}).get("usercontribs", [])
    if not contribs:
        return None

    oldest = contribs[-1].get("timestamp")
    return oldest or None


def iter_contribs_after_timestamp(
    target_user,
    start_timestamp,
    limit=None,
    end_timestamp=None,
    rollbackable_only=False,
    debug_callback=None,
):
    url = "https://commons.wikimedia.org/w/api.php"

    continue_params = None
    yielded = 0

    while True:
        remaining = None

        if limit is not None:
            remaining = max(limit - yielded, 0)

            if remaining == 0:
                break

        params = {
            "action": "query",
            "list": "usercontribs",
            "ucuser": target_user,
            "uclimit": str(min(500, remaining)) if remaining is not None else "500",
            "ucprop": "ids|title|timestamp",
            "ucstart": start_timestamp,
            "ucdir": "newer",
            "format": "json",
        }

        if rollbackable_only:
            params["ucshow"] = "top"

        if end_timestamp:
            params["ucend"] = end_timestamp

        if continue_params:
            params.update(continue_params)

        started = time.perf_counter()
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if callable(debug_callback):
                debug_callback(
                    {
                        "kind": "usercontribs",
                        "params": params,
                        "status_code": resp.status_code,
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                        "response_snippet": resp.text[:_MW_DEBUG_BODY_MAX],
                        "continue": data.get("continue"),
                    }
                )
        except requests.RequestException as e:
            if callable(debug_callback):
                debug_callback(
                    {
                        "kind": "usercontribs",
                        "params": params,
                        "error": f"{type(e).__name__}: {e}",
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    }
                )
            app.logger.error(
                "Failed to fetch contributions for user %s after timestamp %s: %s",
                target_user,
                start_timestamp,
                e,
            )
            raise ValueError(f"Failed to fetch user contributions: {e}") from e

        contribs = data.get("query", {}).get("usercontribs", [])

        for edit in contribs:
            # Strictly after the diff timestamp.
            if edit.get("timestamp") and edit["timestamp"] > start_timestamp:
                yielded += 1
                yield {"title": edit["title"], "user": target_user}

                if limit is not None and yielded >= limit:
                    break

        if limit is not None and yielded >= limit:
            break

        if not data.get("continue"):
            break

        continue_params = data["continue"]

        time.sleep(0.1)

        if yielded >= 10000:
            break


def fetch_contribs_after_timestamp(target_user, start_timestamp, limit=None):
    return list(iter_contribs_after_timestamp(target_user, start_timestamp, limit=limit))


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


@shared_task(ignore_result=True)
def resolve_diff_rollback_job(job_id: int):
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

    def _debug(event: dict) -> None:
        _append_mw_debug(job_id, event)

    try:
        oldid = _extract_oldid(diff)
        _update_diff_payload(job_id, {"oldid": oldid})

        diff_metadata = fetch_diff_author_and_timestamp(oldid, debug_callback=_debug)

        target_user = diff_metadata["user"]
        start_timestamp = diff_metadata["timestamp"]

        try:
            first_uclimit = str(min(500, int(limit))) if limit is not None else "500"
        except (TypeError, ValueError):
            first_uclimit = "500"

        rollbackable_end_timestamp = fetch_rollbackable_window_end_timestamp(
            target_user,
            start_timestamp,
            limit=_ROLLBACKABLE_WINDOW_LIMIT,
            debug_callback=_debug,
        )

        query_debug_payload = {
            "oldid": oldid,
            "resolved_user": target_user,
            "resolved_timestamp": start_timestamp,
            "revision_query": {
                "action": "query",
                "prop": "revisions",
                "revids": str(oldid),
                "rvprop": "ids|user|timestamp",
                "format": "json",
            },
            "contribs_query": {
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
            },
            "rollbackable_window_limit": _ROLLBACKABLE_WINDOW_LIMIT,
            "rollbackable_window_end_timestamp": rollbackable_end_timestamp,
        }

        _update_diff_payload(
            job_id,
            query_debug_payload,
        )

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
                cursor.execute("DELETE FROM rollback_job_items WHERE job_id=%s", (job_id,))

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
                            ("staging", 1 if dry_run else 0, requested_by, batch_id, job_id),
                        )
                        return job_id

                    cursor.execute(
                        """
                        INSERT INTO rollback_jobs
                        (requested_by, status, dry_run, batch_id)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (requested_by, "staging", 1 if dry_run else 0, batch_id),
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
                            **query_debug_payload,
                            "source_job_id": job_id,
                        },
                    )
                    return chunk_job_id

                for item in iter_contribs_after_timestamp(
                    target_user,
                    start_timestamp,
                    limit=limit,
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
                    raise ValueError("No contributions found after the provided diff timestamp")

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
            current_job=f"Processing {total_items} resolved items from diff",
            details=f"Diff resolved successfully into {len(created_job_ids)} job(s)",
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


if not os.environ.get("NOTDEV"):
    from dotenv import load_dotenv

    load_dotenv()


def get_user_groups(username):
    now = time.time()

    cached = _group_cache.get(username)
    if cached and (now - cached["ts"] < GROUP_CACHE_TTL):
        return cached["groups"]

    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "users",
        "ususers": username,
        "usprop": "groups",
        "format": "json",
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        users = data.get("query", {}).get("users", [])
        groups = users[0].get("groups", []) if users else []
    except Exception:
        app.logger.exception("Failed to fetch groups for %s", username)
        groups = []

    _group_cache[username] = {"groups": groups, "ts": now}
    return groups


def is_authorized(username):
    if not username:
        return False

    config = _effective_runtime_authz_config()

    if is_maintainer(username):
        return True

    if username.lower() in config["EXTRA_AUTHORIZED_USERS"]:
        return True

    groups = get_user_groups(username)
    return any(group in ALLOWED_GROUPS for group in groups)


def is_admin_user(username: str) -> bool:
    """Return True if the user has the Commons sysop (admin) right."""
    if not username:
        return False
    return "sysop" in get_user_groups(username)


def is_bot_admin(username: str) -> bool:
    """Return True if the user is one of the hardcoded bot-admin accounts (e.g. chuckbot).

    Bot admins sit at the top of the user hierarchy: chuckbot > maintainer > admin > regular.
    """
    if not username:
        return False
    return username.strip().lower() in BOT_ADMIN_ACCOUNTS


def _can_view_runtime_config(username: str) -> bool:
    if not username:
        return False
    return is_bot_admin(username)


def _can_edit_runtime_config(username: str) -> bool:
    if not username:
        return False
    return (
        is_bot_admin(username)
        and username.strip().lower() == _CONFIG_EDIT_PRIMARY_ACCOUNT
    )


def is_tester(username: str) -> bool:
    """Return True if the user is in the USERS_TESTER env-var list.

    Testers sit between regular users and maintainers: they have access to all
    tools (from_diff, batch, read_all) and a higher rate limit, but no
    cross-user cancel or retry privileges.
    """
    if not username:
        return False
    config = _effective_runtime_authz_config()
    return username.strip().lower() in config["USERS_TESTER"]


def _user_permissions(username: str) -> frozenset:
    """Return the set of permission flags for an already-authenticated user.

    User hierarchy (highest → lowest)
    ----------------------------------
    bot admin (BOT_ADMIN_ACCOUNTS)   — chuckbot and similar accounts
    maintainer (Toolhub maintainers) — includes bot admins
    tester (USERS_TESTER)            — all tools, higher rate limit; no cross-user actions
    admin (Commons sysop)            — can log in; base perms only
    regular user (rollbacker/sysop)  — rollback queue only

    Permission strings
    ------------------
    read_own               — view the user's own jobs
    write                  — submit new rollback jobs
    cancel_own             — cancel the user's own jobs
    retry_own              — retry the user's own jobs
    read_all               — view every user's jobs (all-jobs interface)
    from_diff              — use the rollback-from-diff interface
    batch                  — use the batch rollback interface
    cancel_any             — cancel any non-privileged (regular) user's job
    retry_any              — retry any user's job
    cancel_admin_jobs      — cancel a Commons admin (sysop) user's job; all maintainers
    cancel_maintainer_jobs — cancel a maintainer's job; only bot admins possess this
    config_view            — view runtime config editor/API; bot admins only
    config_edit            — edit runtime config; primary account only (default: chuckbot)
    """
    if not username:
        return frozenset()

    lower = username.lower()
    config = _effective_runtime_authz_config()

    # Read-only users may only view their own jobs.
    if lower in config["USERS_READ_ONLY"]:
        return frozenset({"read_own"})

    # Base permissions granted to every authenticated user.
    perms: set = {"read_own", "write", "cancel_own", "retry_own"}

    if is_maintainer(username):
        # Maintainers are above admins: they can cancel any admin's job.
        perms |= {"read_all", "from_diff", "batch", "cancel_any", "retry_any", "cancel_admin_jobs"}
        # Bot admins (chuckbot) sit above all maintainers and can cancel their jobs too.
        if is_bot_admin(username):
            perms.add("cancel_maintainer_jobs")
    elif is_tester(username):
        # Testers get access to all tool interfaces but no cross-user actions.
        perms |= {"read_all", "from_diff", "batch"}
    else:
        # Per-user grants for non-maintainer, non-tester accounts.
        if lower in config["USERS_GRANTED_FROM_DIFF"]:
            perms.add("from_diff")
        if lower in config["USERS_GRANTED_VIEW_ALL"]:
            perms.add("read_all")
        if lower in config["USERS_GRANTED_BATCH"]:
            perms.add("batch")
        if lower in config["USERS_GRANTED_CANCEL_ANY"]:
            perms.add("cancel_any")
        if lower in config["USERS_GRANTED_RETRY_ANY"]:
            perms.add("retry_any")

    if _can_view_runtime_config(username):
        perms.add("config_view")

    if _can_edit_runtime_config(username):
        perms.add("config_edit")

    return frozenset(perms)


def _check_rate_limit(username: str) -> bool:
    """Return True if the user is within their per-hour job-creation rate limit.

    Tiers
    -----
    maintainer  — never rate-limited.
    tester      — checked against RATE_LIMIT_TESTER_JOBS_PER_HOUR (falls back to
                  RATE_LIMIT_JOBS_PER_HOUR when unset).
    regular     — checked against RATE_LIMIT_JOBS_PER_HOUR.

    When the applicable limit is 0, rate limiting is disabled for that tier.
    Fails open on Redis errors so that a Redis outage does not block job submission.
    """
    # Maintainers are never rate-limited.
    if is_maintainer(username):
        return True

    config = _effective_runtime_authz_config()

    limit = (
        int(config["RATE_LIMIT_TESTER_JOBS_PER_HOUR"])
        if is_tester(username)
        else int(config["RATE_LIMIT_JOBS_PER_HOUR"])
    )

    if limit <= 0:
        return True

    hour_bucket = int(time.time() // 3600)
    key = f"rollback:ratelimit:{username.lower()}:{hour_bucket}"

    try:
        count = r.incr(key)
        if count == 1:
            # First entry in this bucket — expire after two hours for cleanup.
            r.expire(key, 7200)
        return int(count) <= limit
    except Exception:
        app.logger.warning(
            "Rate-limit check failed for %s; failing open.", username
        )
        return True


def _ensure_secret_key():
    configured = app.config.get("SECRET_KEY") or os.environ.get("SECRET_KEY")
    if not configured:
        configured = os.environ.get(
            "FALLBACK_SECRET_KEY",
            "dev-insecure-secret-change-me",
        )

    app.config["SECRET_KEY"] = configured
    return configured


_ensure_secret_key()


def _user_consumer_token():
    key = os.environ.get("USER_OAUTH_CONSUMER_KEY")
    secret = os.environ.get("USER_OAUTH_CONSUMER_SECRET")

    if not key or not secret:
        return None

    return mwoauth.ConsumerToken(key, secret)


def _serialize_request_token(request_token):
    if isinstance(request_token, dict):
        return request_token

    token_fields = getattr(request_token, "_fields", None)

    if token_fields:
        return dict(zip(token_fields, request_token))

    if isinstance(request_token, (tuple, list)) and len(request_token) == 2:
        return {
            "key": request_token[0],
            "secret": request_token[1],
        }

    raise ValueError("Unsupported request token format")


def _deserialize_request_token(payload):
    if not isinstance(payload, dict):
        raise ValueError("request_token payload must be a dict")

    try:
        return mwoauth.RequestToken(**payload)
    except TypeError:
        key = payload.get("key")
        secret = payload.get("secret")

        if key and secret:
            return mwoauth.RequestToken(key, secret)

        raise


def _oauth_callback_url():
    configured = os.environ.get("USER_OAUTH_CALLBACK_URL")

    if configured:
        return configured

    tool_name = os.environ.get("TOOL_NAME") or "buckbot"

    return f"https://{tool_name}.toolforge.org/mas-oauth-callback"


def _rollback_api_actor():
    username = session.get("username")

    if username:
        return username

    status_token = request.headers.get("X-Status-Token")
    expected_token = os.environ.get("STATUS_API_TOKEN")

    if (
        status_token
        and expected_token
        and secrets.compare_digest(status_token, expected_token)
    ):
        return os.environ.get("STATUS_API_USER", "status-site")

    return None


def _parse_bool(value, default=False):
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in {"1", "true", "yes", "on"}:
            return True

        if normalized in {"0", "false", "no", "off", ""}:
            return False

    return default


@app.route("/goto")
def goto():
    username = session.get("username")
    tab = request.args.get("tab")

    if not username:
        return redirect(url_for("login", referrer="/goto?tab=" + str(tab)))

    if tab == "rollback-queue":
        return redirect("/rollback-queue")

    if tab == "rollback-batch":
        if "batch" not in _user_permissions(username):
            abort(403)
        return redirect("/rollback_batch")

    if tab == "rollback-all-jobs":
        if "read_all" not in _user_permissions(username):
            abort(403)
        return redirect("/rollback-queue/all-jobs")

    if tab == "rollback-from-diff":
        if "from_diff" not in _user_permissions(username):
            abort(403)
        return redirect("/rollback-from-diff")

    if tab == "rollback-config":
        if not _can_view_runtime_config(username):
            abort(403)
        return redirect("/rollback-config")

    if tab == "documentation":
        return redirect(
            "https://commons.wikimedia.org/wiki/User:Alachuckthebuck/unbuckbot"
        )

    return redirect("/rollback-queue")


@app.route("/api/v1/rollback/worker")
def worker_status():
    hb = r.get("rollback:worker:heartbeat")

    if not hb:
        return jsonify({"status": "offline"})

    age = time.time() - float(hb)

    return jsonify(
        {
            "status": "online",
            "last_seen": age,
        }
    )


@app.route("/api/v1/rollback/jobs/progress")
def batch_job_progress():
    if session.get("username") is None:
        return jsonify({"detail": "Not authenticated"}), 401

    ids = request.args.get("ids", "")

    if not ids:
        return jsonify({"jobs": []})

    job_ids = [int(x) for x in ids.split(",") if x.strip()]

    jobs = []

    for jid in job_ids:
        p = get_progress(jid)

        if p:
            jobs.append(
                {
                    "id": jid,
                    **p,
                }
            )

    return jsonify({"jobs": jobs})


@app.route("/rollback-queue")
def rollback_queue_ui():
    username = session.get("username")

    jobs = []

    if username:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, requested_by, status, dry_run, created_at
                    FROM rollback_jobs
                    WHERE requested_by=%s
                      AND (
                        status NOT IN ('completed', 'failed', 'canceled')
                        OR (status='failed' AND created_at >= (NOW() - INTERVAL 24 HOUR))
                                                OR (status='completed' AND created_at >= (NOW() - INTERVAL 2 HOUR))
                      )
                    ORDER BY id DESC
                    LIMIT 100
                    """,
                    (username,),
                )

                jobs = cursor.fetchall()

    return render_template(
        "rollback_queue.html",
        jobs=jobs,
        username=username,
        is_maintainer=bool(username and is_maintainer(username)),
        type="rollback-queue",
    )


@app.route("/api/v1/rollback/from-diff", methods=["POST"])
def rollback_from_diff_api():
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    if "from_diff" not in _user_permissions(username):
        return jsonify({"detail": "Forbidden"}), 403

    payload = request.get_json(silent=True) or {}

    diff = request.args.get("diff") or payload.get("diff") or request.form.get("diff")
    summary = (
        request.args.get("summary")
        or payload.get("summary")
        or request.form.get("summary")
        or ""
    )
    dry_run_raw = (
        request.args.get("dry_run")
        if request.args.get("dry_run") is not None
        else payload.get("dry_run", request.form.get("dry_run"))
    )
    limit_raw = (
        request.args.get("limit")
        if request.args.get("limit") is not None
        else payload.get("limit", request.form.get("limit"))
    )

    if diff in (None, ""):
        return jsonify({"detail": "Missing required parameter: diff"}), 400

    limit = None

    if limit_raw not in (None, ""):
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            return jsonify({"detail": "limit must be an integer"}), 400

        if limit <= 0:
            return jsonify({"detail": "limit must be a positive integer"}), 400

        if limit > 10000:
            return jsonify({"detail": "limit must be <= 10000"}), 400

    dry_run = _parse_bool(dry_run_raw, default=False)

    batch_id = int(time.time() * 1000)

    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO rollback_jobs
                    (requested_by, status, dry_run, batch_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (username, "resolving", 1 if dry_run else 0, batch_id),
                )
                job_id = cursor.lastrowid
            conn.commit()

        _store_diff_payload(
            job_id,
            {
                "diff": diff,
                "summary": summary,
                "requested_by": username,
                "dry_run": dry_run,
                "limit": limit,
            },
        )
        status_updater.update_wiki_status(
            editing="Resolving diff",
            current_job=f"Resolving diff for job {job_id}",
            details=f"Diff: {diff}, limit: {limit}",
        )
        resolve_diff_rollback_job.delay(job_id)
    except Exception as e:
        logging.exception("Error in rollback_from_diff_api")
        return jsonify({"detail": "Failed to create rollback jobs: " + str(e)}), 500

    return jsonify(
        {
            "job_id": job_id,
            "job_ids": [job_id],
            "chunks": 1,
            "batch_id": batch_id,
            "total_items": 0,
            "status": "resolving",
            "diff": diff,
            "dry_run": dry_run,
            "limit": limit,
        }
    )


@app.route("/rollback-from-diff")
def rollback_from_diff_page():
    username = session.get("username")

    if not username:
        abort(401)

    if "from_diff" not in _user_permissions(username):
        abort(403)

    return render_template(
        "rollback_from_diff.html",
        username=username,
        max_limit=10000,
        default_limit=100,
        type="rollback-from-diff",
    )


@app.route("/rollback-queue/all-jobs")
def rollback_queue_all_jobs_ui():
    username = session.get("username")

    if not username:
        abort(401)

    if "read_all" not in _user_permissions(username):
        abort(403)

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    j.id,
                    j.requested_by,
                    j.status,
                    j.dry_run,
                    j.created_at,
                    COUNT(i.id) AS total_items,
                    COALESCE(SUM(CASE WHEN i.status='completed' THEN 1 ELSE 0 END), 0) AS completed_items,
                    COALESCE(SUM(CASE WHEN i.status='failed' THEN 1 ELSE 0 END), 0) AS failed_items
                FROM rollback_jobs j
                LEFT JOIN rollback_job_items i ON i.job_id = j.id
                GROUP BY j.id, j.requested_by, j.status, j.dry_run, j.created_at
                ORDER BY j.id DESC
                """
            )

            jobs = cursor.fetchall()

    if request.args.get("format") == "json":
        jobs_for_output = []
        for row in jobs:
            job_id, requested_by, status, dry_run, created_at, total, completed, failed = row
            if _maybe_mark_stale_resolving_job_failed(job_id, status, created_at):
                status = "failed"

            jobs_for_output.append(
                {
                    "id": job_id,
                    "requested_by": requested_by,
                    "status": status,
                    "dry_run": bool(dry_run),
                    "created_at": str(created_at),
                    "total": int(total or 0),
                    "completed": int(completed or 0),
                    "failed": int(failed or 0),
                }
            )

        return jsonify(
            {
                "jobs": jobs_for_output
            }
        )

    return render_template(
        "rollback_queue_all_jobs.html",
        jobs=jobs,
        username=username,
        type="rollback-all-jobs",
    )


@app.route("/rollback_batch")
def rollback_batch():
    username = session.get("username")

    if not username:
        abort(401)

    if "batch" not in _user_permissions(username):
        abort(403)

    return render_template(
        "batch_rollback.html",
        username=username,
        type="batch-rollback",
    )


@app.route("/rollback-config")
def rollback_config_ui():
    username = session.get("username")

    if not username:
        abort(401)

    if not _can_view_runtime_config(username):
        abort(403)

    return render_template(
        "runtime_config.html",
        username=username,
        can_edit_config=_can_edit_runtime_config(username),
        type="runtime-config",
    )


@app.route("/api/v1/config/authz", methods=["GET"])
def get_runtime_authz_api():
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    if not _can_view_runtime_config(username):
        return jsonify({"detail": "Forbidden"}), 403

    config = _effective_runtime_authz_config()
    return jsonify(
        {
            "config": _serialize_runtime_authz_config(config),
            "can_edit": _can_edit_runtime_config(username),
            "editable_keys": _RUNTIME_AUTHZ_ALLOWED_KEYS,
        }
    )


@app.route("/api/v1/config/authz", methods=["PUT"])
def update_runtime_authz_api():
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    if not _can_edit_runtime_config(username):
        return jsonify({"detail": "Forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"detail": "Invalid payload"}), 400

    updates = payload.get("config", payload)
    if not isinstance(updates, dict):
        return jsonify({"detail": "config must be an object"}), 400

    normalized_updates, errors = _normalize_runtime_authz_updates(updates)
    if errors:
        return jsonify({"detail": "; ".join(errors)}), 400

    if not normalized_updates:
        return jsonify({"detail": "No valid config keys supplied"}), 400

    _persist_runtime_authz_updates(normalized_updates, updated_by=username)
    effective = _effective_runtime_authz_config()

    return jsonify(
        {
            "ok": True,
            "config": _serialize_runtime_authz_config(effective),
            "can_edit": _can_edit_runtime_config(username),
            "editable_keys": _RUNTIME_AUTHZ_ALLOWED_KEYS,
        }
    )


@app.route("/api/v1/rollback/jobs", methods=["GET"])
def list_rollback_jobs():
    username = session.get("username")
    if username is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, requested_by, status, dry_run, created_at
                FROM rollback_jobs
                WHERE requested_by=%s
                                    AND (
                                        status NOT IN ('completed', 'failed', 'canceled')
                                        OR (status='failed' AND created_at >= (NOW() - INTERVAL 24 HOUR))
                                        OR (status='completed' AND created_at >= (NOW() - INTERVAL 2 HOUR))
                                    )
                ORDER BY id DESC
                LIMIT 100
                """,
                (username,),
            )

            jobs = cursor.fetchall()

    return jsonify(
        {
            "jobs": [
                {
                    "id": row[0],
                    "requested_by": row[1],
                    "status": row[2],
                    "dry_run": bool(row[3]),
                    "created_at": str(row[4]),
                }
                for row in jobs
            ]
        }
    )


@app.route("/api/v1/rollback/jobs", methods=["POST"])
def create_rollback_job():
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    perms = _user_permissions(actor)

    if "write" not in perms:
        return jsonify({"detail": "Forbidden: write access required"}), 403

    if not _check_rate_limit(actor):
        return jsonify({"detail": "Rate limit exceeded; try again later"}), 429

    payload = request.get_json(silent=True) or {}

    requested_by = payload.get("requested_by") or actor
    items = payload.get("items") or payload.get("files") or []
    dry_run = _parse_bool(payload.get("dry_run", False), default=False)

    raw_batch_id = payload.get("batch_id")

    if raw_batch_id in (None, ""):
        batch_id = int(time.time() * 1000)
    else:
        try:
            batch_id = int(raw_batch_id)
        except (TypeError, ValueError):
            return jsonify({"detail": "batch_id must be an integer"}), 400

        if batch_id <= 0:
            return jsonify({"detail": "batch_id must be a positive integer"}), 400

    if requested_by != actor:
        return jsonify({"detail": "requested_by must match authenticated user"}), 403

    if not isinstance(items, list) or len(items) == 0:
        return jsonify({"detail": "items must be a non-empty list"}), 400

    if len(items) > 1000:
        return jsonify({"detail": "Too many rollback items"}), 400

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
                    title = (item.get("title") or item.get("file") or "").strip()
                    user = (item.get("user") or "").strip()
                    summary = item.get("summary")

                    if not title or not user:
                        continue

                    cursor.execute(
                        """
                        INSERT INTO rollback_job_items
                        (job_id, file_title, target_user, summary, status)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (job_id, title, user, summary, "queued"),
                    )

        conn.commit()

    if not job_ids:
        return jsonify({"detail": "No valid items to process"}), 400

    for jid in job_ids:
        process_rollback_job.delay(jid)

    return jsonify(
        {
            "job_id": job_ids[0],
            "status": "queued",
            "batch_id": batch_id,
            "job_ids": job_ids,
            "chunks": len(job_ids),
        }
    )


@app.route("/api/v1/rollback/jobs/<int:job_id>/retry", methods=["POST"])
def retry_job(job_id):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT requested_by FROM rollback_jobs WHERE id=%s",
                (job_id,),
            )

            job = cursor.fetchone()

            if not job:
                return jsonify({"detail": "Job not found"}), 404

            if job[0] != actor:
                if "retry_any" not in _user_permissions(actor):
                    return jsonify({"detail": "Forbidden"}), 403

            cursor.execute(
                "SELECT COUNT(*) FROM rollback_job_items WHERE job_id=%s",
                (job_id,),
            )
            item_count_row = cursor.fetchone()
            item_count = int(item_count_row[0]) if item_count_row else 0

            if item_count == 0:
                payload = _load_diff_payload(job_id)
                if not payload:
                    return jsonify({"detail": "Cannot retry this job without saved diff payload"}), 400

                cursor.execute(
                    "UPDATE rollback_jobs SET status='resolving' WHERE id=%s",
                    (job_id,),
                )
                conn.commit()
                _set_diff_error(job_id, None)
                status_updater.update_wiki_status(
                    editing="Resolving diff",
                    current_job=f"Resolving diff for job {job_id}",
                )
                resolve_diff_rollback_job.delay(job_id)
                return jsonify({"job_id": job_id, "status": "resolving"})

            cursor.execute(
                "UPDATE rollback_jobs SET status='queued' WHERE id=%s",
                (job_id,),
            )

            cursor.execute(
                """
                UPDATE rollback_job_items
                SET status='queued', error=NULL
                WHERE job_id=%s
                """,
                (job_id,),
            )

        conn.commit()

    status_updater.update_wiki_status(
        editing="Actively editing",
        current_job=f"Retrying job {job_id}",
    )
    process_rollback_job.delay(job_id)

    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/api/v1/rollback/jobs/<int:job_id>", methods=["DELETE"])
def cancel_rollback_job(job_id):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, requested_by, status
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )

            job = cursor.fetchone()

            if not job:
                return jsonify({"detail": "Job not found"}), 404

            if job[1] != actor:
                actor_perms = _user_permissions(actor)
                # Fast-path: actors with no cross-user cancel permission are always denied.
                if "cancel_any" not in actor_perms and not is_maintainer(actor):
                    return jsonify({"detail": "Forbidden"}), 403

                # Tier check: the required privilege depends on the job owner's level.
                # Hierarchy: bot admin > maintainer > admin (sysop) > regular user.
                job_owner = job[1]
                if is_bot_admin(job_owner):
                    # Bot-admin job: only another bot admin may cancel it.
                    if "cancel_maintainer_jobs" not in actor_perms:
                        return jsonify({"detail": "Forbidden: canceling a bot-admin's job requires bot-admin rights"}), 403
                elif is_maintainer(job_owner):
                    # Regular maintainer's job: any maintainer (or bot admin) may cancel it.
                    if not is_maintainer(actor):
                        return jsonify({"detail": "Forbidden: canceling a maintainer's job requires maintainer rights"}), 403
                elif is_admin_user(job_owner):
                    # Admin job: any maintainer (or bot admin) may cancel it.
                    if "cancel_admin_jobs" not in actor_perms:
                        return jsonify({"detail": "Forbidden: canceling an admin's job requires maintainer rights"}), 403
                # else: regular user's job; cancel_any is sufficient (already checked above).

            if job[2] in {"completed", "failed", "canceled"}:
                return jsonify({"job_id": job_id, "status": job[2]})

            cursor.execute(
                "UPDATE rollback_jobs SET status=%s WHERE id=%s",
                ("canceled", job_id),
            )

            cursor.execute(
                """
                UPDATE rollback_job_items
                SET status=%s, error=%s
                WHERE job_id=%s AND status IN (%s, %s, %s, %s)
                """,
                ("canceled", "Canceled by requester", job_id, "queued", "running", "resolving", "staging"),
            )

        conn.commit()

    status_updater.update_wiki_status(
        editing="Idle",
        last_job=f"Job {job_id} canceled by {actor}",
    )
    _set_diff_error(job_id, None)

    return jsonify({"job_id": job_id, "status": "canceled"})


@app.route("/api/v1/rollback/jobs/<int:job_id>")
def get_rollback_job(job_id):
    username = session.get("username")

    if username is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, requested_by, status, dry_run, created_at
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )

            job = cursor.fetchone()

            if not job:
                return jsonify({"detail": "Job not found"}), 404

            if job[1] != username and "read_all" not in _user_permissions(username):
                return jsonify({"detail": "Forbidden"}), 403

            cursor.execute(
                """
                SELECT id, file_title, target_user, summary, status, error
                FROM rollback_job_items
                WHERE job_id=%s
                ORDER BY id ASC
                """,
                (job_id,),
            )

            items = cursor.fetchall()

    if _maybe_mark_stale_resolving_job_failed(job[0], job[2], job[4]):
        job = (job[0], job[1], "failed", job[3], job[4])

    if request.args.get("format") == "log":
        lines = []

        for item in items:
            item_id, title, target_user, _summary, status, error = item
            line = f"item_id={item_id} status={status} title={title} user={target_user}"

            if error:
                line += f" error={error}"

            lines.append(line)

        body = "\n".join(lines) + ("\n" if lines else "")
        return Response(body, mimetype="text/plain")

    diff_payload = _load_diff_payload(job_id) or {}
    diff_error = r.get(_diff_error_key(job_id))
    if not isinstance(diff_error, str):
        diff_error = None

    return jsonify(
        {
            "id": job[0],
            "requested_by": job[1],
            "status": job[2],
            "dry_run": bool(job[3]),
            "created_at": str(job[4]),
            "total": len(items),
            "completed": len([x for x in items if x[4] == "completed"]),
            "failed": len([x for x in items if x[4] == "failed"]),
            "error": diff_error,
            "diff": diff_payload.get("diff"),
            "oldid": diff_payload.get("oldid"),
            "resolved_user": diff_payload.get("resolved_user"),
            "resolved_timestamp": diff_payload.get("resolved_timestamp"),
            "revision_query": diff_payload.get("revision_query"),
            "contribs_query": diff_payload.get("contribs_query"),
            "mw_debug": diff_payload.get("mw_debug", []),
            "items": [
                {
                    "id": x[0],
                    "title": x[1],
                    "user": x[2],
                    "summary": x[3],
                    "status": x[4],
                    "error": x[5],
                }
                for x in items
            ],
        }
    )


@app.route("/")
def index():
    return render_template(
        "index.html",
        username=session.get("username"),
        type="index",
    )


@app.route("/login")
def login():
    _ensure_secret_key()

    if request.args.get("referrer"):
        session["referrer"] = request.args.get("referrer")

    consumer_token = _user_consumer_token()

    if consumer_token is None:
        app.logger.error("Missing USER_OAUTH_CONSUMER_KEY/USER_OAUTH_CONSUMER_SECRET")
        return redirect(url_for("index"))

    try:
        redirect_loc, request_token = mwoauth.initiate(
            "https://meta.wikimedia.org",
            consumer_token,
            callback=_oauth_callback_url(),
        )
    except Exception:
        app.logger.exception("mwoauth.initiate failed")
        return redirect(url_for("index"))

    try:
        session["request_token"] = _serialize_request_token(request_token)
    except Exception:
        app.logger.exception("Unable to serialize OAuth request token")
        return redirect(url_for("index"))

    return redirect(redirect_loc)


@app.route("/mas-oauth-callback")
@app.route("/oauth-callback")
@app.route("/mwoauth-callback")
@app.route("/buckbot-oauth-callback")
def oauth_callback():
    _ensure_secret_key()

    if "request_token" not in session:
        return redirect(url_for("index"))

    consumer_token = _user_consumer_token()

    if consumer_token is None:
        app.logger.error("Missing USER_OAUTH_CONSUMER_KEY/USER_OAUTH_CONSUMER_SECRET")
        return redirect(url_for("index"))

    authenticated = False

    try:
        access_token = mwoauth.complete(
            "https://meta.wikimedia.org/w/index.php",
            consumer_token,
            _deserialize_request_token(session["request_token"]),
            request.query_string,
        )
        identity = mwoauth.identify(
            "https://meta.wikimedia.org/w/index.php",
            consumer_token,
            access_token,
        )
    except Exception:
        app.logger.exception("OAuth authentication failed")
    else:
        username = identity["username"]

        if not is_authorized(username):
            session.clear()
            return "This tool is restricted to Commons admins and maintainers.", 403

        session["access_token"] = dict(zip(access_token._fields, access_token))
        session["username"] = username
        session["authorized"] = True
        session["is_maintainer"] = bool(is_maintainer(username))
        session["is_admin"] = "sysop" in get_user_groups(username)
        authenticated = True

    referrer = session.get("referrer")
    session["referrer"] = None

    if authenticated:
        return redirect(referrer or "/")

    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))
