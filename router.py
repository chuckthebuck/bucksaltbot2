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
from rollback_queue import (
    process_rollback_job,
    resolve_diff_rollback_job_task as resolve_diff_rollback_job,
)
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

_CONFIG_EDIT_PRIMARY_ACCOUNT = (
    os.getenv("CONFIG_EDIT_PRIMARY_ACCOUNT", "chuckbot").strip().lower()
)

_USER_GRANT_RIGHTS = {
    "from_diff",
    "batch",
    "view_all",
    "cancel_any",
    "retry_any",
    "from_diff_dry_run_only",
}

_USER_GRANT_GROUPS = {
    "viewer": {"view_all"},
    "diff": {"from_diff"},
    "diff_dry_run": {"from_diff", "from_diff_dry_run_only"},
    "batch": {"batch"},
    "support": {"view_all", "retry_any"},
    "operator": {"view_all", "from_diff", "batch", "cancel_any", "retry_any"},
}

_USER_IMPLICIT_FLAGS = (
    "bot_admin",
    "maintainer",
    "tester",
    "read_only",
    "extra_authorized",
)

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

_JSON_CONFIG_KEYS = {
    "USER_GRANTS_JSON",
}

_RUNTIME_AUTHZ_ALLOWED_KEYS = sorted(
    _USER_SET_CONFIG_KEYS | _INT_CONFIG_KEYS | _JSON_CONFIG_KEYS
)
_RUNTIME_AUTHZ_CACHE_TTL = 60
_runtime_authz_cache = None
_runtime_authz_cache_expiry = 0.0


def _parse_user_csv(raw_value: str) -> set[str]:
    return {u.strip().lower() for u in (raw_value or "").split(",") if u.strip()}


def _normalize_username(raw_value: str) -> str:
    cleaned = str(raw_value or "").strip()

    if cleaned.lower().startswith("user:"):
        cleaned = cleaned[5:].strip()

    if len(cleaned) >= 2 and (
        (cleaned[0] == '"' and cleaned[-1] == '"')
        or (cleaned[0] == "'" and cleaned[-1] == "'")
    ):
        cleaned = cleaned[1:-1].strip()

    cleaned = " ".join(cleaned.replace("_", " ").split())
    return cleaned.lower()


def _normalize_grant_atom(atom: str) -> str:
    normalized = str(atom or "").strip().lower().replace(" ", "_")
    if normalized == "read_all":
        return "view_all"
    return normalized


def _normalize_user_grants_map_input(value, key: str) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{key} must be valid JSON") from exc

    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object mapping username to grants")

    normalized = {}

    for raw_user, raw_grants in value.items():
        user = _normalize_username(str(raw_user))
        if not user:
            continue

        atoms = []
        if isinstance(raw_grants, dict):
            rights = raw_grants.get("rights", [])
            groups = raw_grants.get("groups", [])
            if isinstance(rights, str):
                rights = [part.strip() for part in rights.split(",") if part.strip()]
            if isinstance(groups, str):
                groups = [part.strip() for part in groups.split(",") if part.strip()]
            if isinstance(groups, list):
                atoms.extend([f"group:{g}" for g in groups])
            if isinstance(rights, list):
                atoms.extend([str(r) for r in rights])
        elif isinstance(raw_grants, list):
            atoms = [str(item) for item in raw_grants]
        elif isinstance(raw_grants, str):
            atoms = [part.strip() for part in raw_grants.replace("\n", ",").split(",")]
        else:
            raise ValueError(f"{key}.{user} must be a list/string/object")

        user_atoms = set()
        for atom in atoms:
            normalized_atom = _normalize_grant_atom(atom)
            if not normalized_atom:
                continue

            if normalized_atom.startswith("group:"):
                group_name = normalized_atom.split(":", 1)[1]
                if group_name not in _USER_GRANT_GROUPS:
                    raise ValueError(f"Unknown grant group '{group_name}' for {user}")
                user_atoms.add(normalized_atom)
                continue

            if normalized_atom in _USER_GRANT_GROUPS:
                user_atoms.add(f"group:{normalized_atom}")
                continue

            if normalized_atom not in _USER_GRANT_RIGHTS:
                raise ValueError(f"Unknown right '{normalized_atom}' for {user}")

            user_atoms.add(normalized_atom)

        if user_atoms:
            normalized[user] = sorted(user_atoms)

    if len(normalized) > 1000:
        raise ValueError(f"{key} cannot contain more than 1000 users")

    return normalized


def _expand_user_grants(config: dict, username: str) -> set[str]:
    user = _normalize_username(username)
    if not user:
        return set()

    grants_map = config.get("USER_GRANTS_JSON") or {}
    atoms = grants_map.get(user) or []
    expanded = set()

    for raw_atom in atoms:
        atom = _normalize_grant_atom(raw_atom)
        if not atom:
            continue

        if atom.startswith("group:"):
            group_name = atom.split(":", 1)[1]
            expanded |= _USER_GRANT_GROUPS.get(group_name, set())
            continue

        if atom in _USER_GRANT_GROUPS:
            expanded |= _USER_GRANT_GROUPS[atom]
            continue

        if atom in _USER_GRANT_RIGHTS:
            expanded.add(atom)

    return expanded


def _get_user_grants_payload(target_username: str, config: dict) -> dict:
    normalized_username = _normalize_username(target_username)
    grants_map = config.get("USER_GRANTS_JSON") or {}
    atoms = list(grants_map.get(normalized_username, []))

    groups = sorted(
        [atom.split(":", 1)[1] for atom in atoms if atom.startswith("group:")]
    )
    rights = sorted([atom for atom in atoms if not atom.startswith("group:")])
    expanded_rights = sorted(_expand_user_grants(config, normalized_username))

    implicit = {
        "bot_admin": bool(is_bot_admin(normalized_username)),
        "maintainer": bool(is_maintainer(normalized_username)),
        "tester": bool(normalized_username in config["USERS_TESTER"]),
        "read_only": bool(normalized_username in config["USERS_READ_ONLY"]),
        "extra_authorized": bool(
            normalized_username in config["EXTRA_AUTHORIZED_USERS"]
        ),
    }

    return {
        "username": target_username,
        "normalized_username": normalized_username,
        "atoms": sorted(atoms),
        "groups": groups,
        "rights": rights,
        "expanded_rights": expanded_rights,
        "implicit": implicit,
    }


def _parse_user_grants_env(raw_value: str) -> dict:
    if not raw_value:
        return {}

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        app.logger.warning("Invalid USER_GRANTS_JSON env var; ignoring.")
        return {}

    try:
        return _normalize_user_grants_map_input(parsed, "USER_GRANTS_JSON")
    except ValueError as exc:
        app.logger.warning("Invalid USER_GRANTS_JSON env var; ignoring: %s", exc)
        return {}


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
        "USER_GRANTS_JSON": _parse_user_grants_env(os.getenv("USER_GRANTS_JSON", "")),
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
            continue

        if key in _JSON_CONFIG_KEYS:
            try:
                overrides[key] = _normalize_user_grants_map_input(raw_value, key)
            except ValueError:
                overrides[key] = defaults.get(key, {})

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
        elif key in _JSON_CONFIG_KEYS:
            output[key] = value or {}
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

        lowered = _normalize_username(item)

        if not lowered:
            continue

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
            continue

        if key in _JSON_CONFIG_KEYS:
            try:
                normalized[key] = _normalize_user_grants_map_input(value, key)
            except ValueError as exc:
                errors.append(str(exc))

    return normalized, errors


def _persist_runtime_authz_updates(updates: dict, updated_by: str) -> None:
    rows = {}
    for key, value in updates.items():
        if key in _USER_SET_CONFIG_KEYS:
            rows[key] = ",".join(value)
        elif key in _JSON_CONFIG_KEYS:
            rows[key] = json.dumps(value, sort_keys=True)
        else:
            rows[key] = str(value)

    upsert_runtime_config(rows, updated_by=updated_by)
    _invalidate_runtime_authz_cache()


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


def _normalize_target_user_input(raw_value):
    cleaned = str(raw_value or "").strip()

    if cleaned.lower().startswith("user:"):
        cleaned = cleaned[5:].strip()

    if len(cleaned) >= 2 and (
        (cleaned[0] == '"' and cleaned[-1] == '"')
        or (cleaned[0] == "'" and cleaned[-1] == "'")
    ):
        cleaned = cleaned[1:-1].strip()

    return " ".join(cleaned.replace("_", " ").split())


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
        raise ValueError(
            f"Failed to fetch rollbackable contribution window: {e}"
        ) from e

    contribs = data.get("query", {}).get("usercontribs", [])
    if not contribs:
        return None

    oldest = contribs[-1].get("timestamp")
    return oldest or None


def fetch_recent_rollbackable_contribs(
    target_user,
    limit=_ACCOUNT_ROLLBACK_MAX_LIMIT,
    debug_callback=None,
):
    """Return latest rollbackable contributions for a target account.

    This powers account-wide rollback requests and is hard-capped at 500 items
    to match Action API ``usercontribs`` constraints.
    """
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "usercontribs",
        "ucuser": target_user,
        "uclimit": str(min(_ACCOUNT_ROLLBACK_MAX_LIMIT, int(limit))),
        "ucprop": "ids|title|timestamp",
        "ucshow": "top",
        "ucstart": _utc_now_iso(),
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
                    "kind": "usercontribs-account",
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
                    "kind": "usercontribs-account",
                    "params": params,
                    "error": f"{type(e).__name__}: {e}",
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                }
            )
        raise ValueError(
            f"Failed to fetch recent rollbackable contributions: {e}"
        ) from e

    contribs = data.get("query", {}).get("usercontribs", [])
    results = []

    for edit in contribs:
        title = edit.get("title")
        if not title:
            continue
        results.append({"title": title, "user": target_user})

    return results


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
    return list(
        iter_contribs_after_timestamp(target_user, start_timestamp, limit=limit)
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
    view_all               — alias for read_all (for grant semantics)
    from_diff              — use the rollback-from-diff interface
    from_diff_dry_run_only — can use from-diff only when dry_run=true
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
        perms |= {
            "read_all",
            "from_diff",
            "batch",
            "cancel_any",
            "retry_any",
            "cancel_admin_jobs",
        }
        # Bot admins (chuckbot) sit above all maintainers and can cancel their jobs too.
        if is_bot_admin(username):
            perms.add("cancel_maintainer_jobs")
    elif is_tester(username):
        # Testers get access to all tool interfaces but no cross-user actions.
        perms |= {"read_all", "from_diff", "batch"}
    else:
        # Legacy per-right grants for non-maintainer, non-tester accounts.
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

        # User-centric grants (MediaWiki-style): username -> rights/groups.
        expanded_grants = _expand_user_grants(config, lower)
        if "from_diff_dry_run_only" in expanded_grants:
            # Dry-run-only implies from_diff access but only in dry-run mode.
            perms |= {"from_diff", "from_diff_dry_run_only"}
        if "from_diff" in expanded_grants:
            perms.add("from_diff")
        if "view_all" in expanded_grants:
            perms |= {"read_all", "view_all"}
        if "batch" in expanded_grants:
            perms.add("batch")
        if "cancel_any" in expanded_grants:
            perms.add("cancel_any")
        if "retry_any" in expanded_grants:
            perms.add("retry_any")

    if "read_all" in perms:
        perms.add("view_all")

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
        app.logger.warning("Rate-limit check failed for %s; failing open.", username)
        return True


@app.context_processor
def inject_nav_capabilities():
    """Expose template flags so nav tabs only render when actionable."""
    username = session.get("username")
    if not username:
        return {
            "nav_can_write": False,
            "nav_can_all_jobs": False,
            "nav_is_admin": False,
        }

    perms = _user_permissions(username)
    is_admin = bool(session.get("is_admin") or is_admin_user(username))

    return {
        "nav_can_write": bool("write" in perms),
        "nav_can_all_jobs": bool("read_all" in perms or is_admin),
        "nav_is_admin": is_admin,
    }


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


def _normalize_request_type(raw_value) -> str:
    value = str(raw_value or "").strip().lower()
    if value in _ALLOWED_REQUEST_TYPES:
        return value
    return _REQUEST_TYPE_QUEUE


def _normalize_request_endpoint(raw_value) -> str | None:
    value = str(raw_value or "").strip().lower().replace("-", "_")
    return value or None


def _approval_requirement_for_request(
    request_type: str, requested_endpoint: str | None
) -> str | None:
    if request_type == _REQUEST_TYPE_BATCH or requested_endpoint == _ENDPOINT_BATCH:
        return _APPROVAL_REQUIRED_ADMIN
    if request_type == _REQUEST_TYPE_DIFF:
        return _APPROVAL_REQUIRED_MAINTAINER
    return None


def _can_actor_approve(actor: str, required_level: str | None) -> bool:
    if not actor or not required_level:
        return False

    if required_level == _APPROVAL_REQUIRED_MAINTAINER:
        return is_maintainer(actor)

    if required_level == _APPROVAL_REQUIRED_ADMIN:
        return is_maintainer(actor) or is_admin_user(actor)

    return False


def _can_review_requests(username: str) -> bool:
    if not username:
        return False
    return is_maintainer(username) or is_admin_user(username)


def _can_run_live(actor: str, requested_by: str, approval_required: str | None) -> bool:
    """Return whether *actor* may re-run a completed dry-run job live."""
    if not actor:
        return False

    if actor == requested_by:
        return True

    if _can_actor_approve(actor, approval_required):
        return True

    return "retry_any" in _user_permissions(actor)


def _should_autoapprove_request(actor: str, required_level: str | None) -> bool:
    """Return True when test-mode requests should skip manual approval.

    This is intentionally restricted to test runs with an explicit opt-in env var
    to avoid changing production approval workflows.
    """
    if not actor or not required_level:
        return False

    if not app.config.get("TESTING"):
        return False

    if not _parse_bool(os.environ.get("LIVE_TEST_AUTO_APPROVE_REQUESTS"), default=False):
        return False

    return _can_actor_approve(actor, required_level)


def _pending_batch_request_job_ids(
    cursor, batch_id: int, request_type: str
) -> list[int]:
    cursor.execute(
        """
        SELECT id
        FROM rollback_jobs
        WHERE batch_id=%s AND request_type=%s AND status=%s
        ORDER BY id ASC
        """,
        (batch_id, request_type, _REQUEST_STATUS_PENDING_APPROVAL),
    )
    return [int(row[0]) for row in cursor.fetchall()]


def _request_payload_has_diff_anchor(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False

    for key in ("diff", "oldid", "resolved_timestamp"):
        if payload.get(key) not in (None, ""):
            return True

    return False


def _compute_diff_request_preview(
    job_id: int,
    payload: dict,
    endpoint: str,
    full_from_diff: bool = True,
) -> dict:
    """Compute and cache preview edits for a diff-style request endpoint."""
    if endpoint not in _ALLOWED_DIFF_REQUEST_ENDPOINTS:
        raise ValueError("Unsupported endpoint for diff request preview")

    preview_by_endpoint = payload.get("preview_by_endpoint")
    if not isinstance(preview_by_endpoint, dict):
        preview_by_endpoint = {}

    cache_key = f"{endpoint}:{'full' if (endpoint == _ENDPOINT_FROM_DIFF and full_from_diff) else 'limited'}"
    cached = preview_by_endpoint.get(cache_key)
    if isinstance(cached, dict) and isinstance(cached.get("items"), list):
        return cached

    limit_raw = payload.get("limit")
    limit = None
    if limit_raw not in (None, ""):
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ValueError("limit must be an integer")
        if limit <= 0:
            raise ValueError("limit must be a positive integer")

    diff = payload.get("diff")
    target_user = _normalize_target_user_input(payload.get("target_user"))
    oldid = payload.get("oldid")
    start_timestamp = payload.get("resolved_timestamp")

    if diff not in (None, ""):
        if oldid in (None, ""):
            oldid = _extract_oldid(diff)
        diff_metadata = fetch_diff_author_and_timestamp(oldid)
        if not target_user:
            target_user = diff_metadata["user"]
        if not start_timestamp:
            start_timestamp = diff_metadata["timestamp"]

    if not target_user:
        raise ValueError("Unable to resolve target user for request preview")

    items: list[dict] = []
    rollbackable_end_timestamp = None

    if endpoint == _ENDPOINT_FROM_ACCOUNT:
        effective_limit = limit or _ACCOUNT_ROLLBACK_MAX_LIMIT
        if effective_limit > _ACCOUNT_ROLLBACK_MAX_LIMIT:
            raise ValueError(f"limit must be <= {_ACCOUNT_ROLLBACK_MAX_LIMIT}")
        items = fetch_recent_rollbackable_contribs(target_user, limit=effective_limit)
    else:
        if not start_timestamp:
            raise ValueError("Diff timestamp is required for from-diff preview")
        rollbackable_end_timestamp = fetch_rollbackable_window_end_timestamp(
            target_user,
            start_timestamp,
            limit=_ROLLBACKABLE_WINDOW_LIMIT,
        )
        items = list(
            iter_contribs_after_timestamp(
                target_user,
                start_timestamp,
                limit=None if full_from_diff else limit,
                end_timestamp=rollbackable_end_timestamp,
                rollbackable_only=True,
            )
        )

    preview_payload = {
        "endpoint": endpoint,
        "oldid": oldid,
        "resolved_user": target_user,
        "resolved_timestamp": start_timestamp,
        "rollbackable_window_end_timestamp": rollbackable_end_timestamp,
        "limit": None
        if (endpoint == _ENDPOINT_FROM_DIFF and full_from_diff)
        else limit,
        "request_limit": limit,
        "full_from_diff": bool(endpoint == _ENDPOINT_FROM_DIFF and full_from_diff),
        "total_items": len(items),
        "items": items,
        "generated_at": _utc_now_iso(),
    }

    preview_by_endpoint[cache_key] = preview_payload
    payload["preview_by_endpoint"] = preview_by_endpoint
    _store_diff_payload(job_id, payload)
    return preview_payload


@app.route("/goto")
def goto():
    username = session.get("username")
    tab = request.args.get("tab")

    if not username:
        return redirect(url_for("login", referrer="/goto?tab=" + str(tab)))

    if tab == "rollback-queue":
        return redirect("/rollback-queue")

    if tab == "rollback-batch":
        if "write" not in _user_permissions(username):
            abort(403)
        return redirect("/rollback_batch")

    if tab == "rollback-all-jobs":
        if "read_all" not in _user_permissions(username) and not is_admin_user(
            username
        ):
            abort(403)
        return redirect("/rollback-queue/all-jobs")

    if tab == "rollback-from-diff":
        if "write" not in _user_permissions(username):
            abort(403)
        return redirect("/rollback-from-diff")

    if tab == "rollback-account":
        if "write" not in _user_permissions(username):
            abort(403)
        return redirect("/rollback-account")

    if tab == "rollback-requests":
        return redirect("/rollback-requests")

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

    perms = _user_permissions(username)

    if "write" not in perms and "from_diff" not in perms:
        return jsonify({"detail": "Forbidden: write access required"}), 403

    if not _check_rate_limit(username):
        return jsonify({"detail": "Rate limit exceeded; try again later"}), 429

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

    if "from_diff_dry_run_only" in perms and not dry_run:
        return jsonify(
            {"detail": "Forbidden: from-diff access is limited to dry-run mode"}
        ), 403

    batch_id = int(time.time() * 1000)
    autoapproved = False

    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
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
                        approval_required
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        username,
                        _REQUEST_STATUS_PENDING_APPROVAL,
                        1 if dry_run else 0,
                        batch_id,
                        _REQUEST_TYPE_DIFF,
                        _ENDPOINT_FROM_DIFF,
                        None,
                        _APPROVAL_REQUIRED_MAINTAINER,
                    ),
                )
                job_id = cursor.lastrowid

                autoapproved = _should_autoapprove_request(
                    username,
                    _APPROVAL_REQUIRED_MAINTAINER,
                )
                if autoapproved:
                    cursor.execute(
                        """
                        UPDATE rollback_jobs
                        SET
                            status=%s,
                            approved_endpoint=%s,
                            approved_by=%s,
                            approved_at=CURRENT_TIMESTAMP
                        WHERE id=%s
                        """,
                        ("resolving", _ENDPOINT_FROM_DIFF, username, job_id),
                    )
            conn.commit()

        _store_diff_payload(
            job_id,
            {
                "diff": diff,
                "summary": summary,
                "requested_by": username,
                "dry_run": dry_run,
                "limit": limit,
                "requested_endpoint": _ENDPOINT_FROM_DIFF,
                "approved_endpoint": _ENDPOINT_FROM_DIFF if autoapproved else None,
                "approved_by": username if autoapproved else None,
                "approved_at": _utc_now_iso() if autoapproved else None,
            },
        )

        if autoapproved:
            _set_diff_error(job_id, None)
            status_updater.update_wiki_status(
                editing="Resolving diff",
                current_job=f"Auto-approved diff job {job_id} resolving",
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
            "status": "resolving" if autoapproved else _REQUEST_STATUS_PENDING_APPROVAL,
            "diff": diff,
            "dry_run": dry_run,
            "limit": limit,
            "request_type": _REQUEST_TYPE_DIFF,
            "requested_endpoint": _ENDPOINT_FROM_DIFF,
            "approved_endpoint": _ENDPOINT_FROM_DIFF if autoapproved else None,
            "approved_by": username if autoapproved else None,
            "approval_required": _APPROVAL_REQUIRED_MAINTAINER,
        }
    )


@app.route("/api/v1/rollback/from-account", methods=["POST"])
def rollback_from_account_api():
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    perms = _user_permissions(username)

    if "write" not in perms and "from_diff" not in perms:
        return jsonify({"detail": "Forbidden: write access required"}), 403

    if not _check_rate_limit(username):
        return jsonify({"detail": "Rate limit exceeded; try again later"}), 429

    payload = request.get_json(silent=True) or {}

    target_user_raw = (
        request.args.get("target_user")
        if request.args.get("target_user") is not None
        else payload.get("target_user", request.form.get("target_user"))
    )
    if target_user_raw in (None, ""):
        target_user_raw = (
            request.args.get("user")
            if request.args.get("user") is not None
            else payload.get("user", request.form.get("user"))
        )
    if target_user_raw in (None, ""):
        target_user_raw = (
            request.args.get("account")
            if request.args.get("account") is not None
            else payload.get("account", request.form.get("account"))
        )

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

    target_user = _normalize_target_user_input(target_user_raw)
    if not target_user:
        return jsonify({"detail": "Missing required parameter: target_user"}), 400

    if len(target_user) > 85:
        return jsonify({"detail": "target_user is too long"}), 400

    dry_run = _parse_bool(dry_run_raw, default=False)

    if "from_diff_dry_run_only" in perms and not dry_run:
        return jsonify(
            {"detail": "Forbidden: from-diff access is limited to dry-run mode"}
        ), 403

    limit = _ACCOUNT_ROLLBACK_MAX_LIMIT
    if limit_raw not in (None, ""):
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            return jsonify({"detail": "limit must be an integer"}), 400

        if limit <= 0:
            return jsonify({"detail": "limit must be a positive integer"}), 400

        if limit > _ACCOUNT_ROLLBACK_MAX_LIMIT:
            return jsonify(
                {"detail": f"limit must be <= {_ACCOUNT_ROLLBACK_MAX_LIMIT}"}
            ), 400

    try:
        batch_id = int(time.time() * 1000)
        autoapproved = False

        with get_conn() as conn:
            with conn.cursor() as cursor:
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
                        approval_required
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        username,
                        _REQUEST_STATUS_PENDING_APPROVAL,
                        1 if dry_run else 0,
                        batch_id,
                        _REQUEST_TYPE_DIFF,
                        _ENDPOINT_FROM_ACCOUNT,
                        None,
                        _APPROVAL_REQUIRED_MAINTAINER,
                    ),
                )
                job_id = cursor.lastrowid

                autoapproved = _should_autoapprove_request(
                    username,
                    _APPROVAL_REQUIRED_MAINTAINER,
                )
                if autoapproved:
                    cursor.execute(
                        """
                        UPDATE rollback_jobs
                        SET
                            status=%s,
                            approved_endpoint=%s,
                            approved_by=%s,
                            approved_at=CURRENT_TIMESTAMP
                        WHERE id=%s
                        """,
                        ("resolving", _ENDPOINT_FROM_ACCOUNT, username, job_id),
                    )
            conn.commit()

        _store_diff_payload(
            job_id,
            {
                "target_user": target_user,
                "summary": summary,
                "requested_by": username,
                "dry_run": dry_run,
                "limit": limit,
                "requested_endpoint": _ENDPOINT_FROM_ACCOUNT,
                "approved_endpoint": _ENDPOINT_FROM_ACCOUNT if autoapproved else None,
                "approved_by": username if autoapproved else None,
                "approved_at": _utc_now_iso() if autoapproved else None,
            },
        )

        if autoapproved:
            _set_diff_error(job_id, None)
            status_updater.update_wiki_status(
                editing="Resolving account",
                current_job=f"Auto-approved account job {job_id} resolving",
            )
            resolve_diff_rollback_job.delay(job_id)

    except ValueError as e:
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        logging.exception("Error in rollback_from_account_api")
        return jsonify({"detail": "Failed to create rollback jobs: " + str(e)}), 500

    return jsonify(
        {
            "job_id": job_id,
            "job_ids": [job_id],
            "chunks": 1,
            "batch_id": batch_id,
            "total_items": 0,
            "status": "resolving" if autoapproved else _REQUEST_STATUS_PENDING_APPROVAL,
            "resolved_user": target_user,
            "dry_run": dry_run,
            "limit": limit,
            "request_type": _REQUEST_TYPE_DIFF,
            "requested_endpoint": _ENDPOINT_FROM_ACCOUNT,
            "approved_endpoint": _ENDPOINT_FROM_ACCOUNT if autoapproved else None,
            "approved_by": username if autoapproved else None,
            "approval_required": _APPROVAL_REQUIRED_MAINTAINER,
        }
    )


@app.route("/rollback-from-diff")
def rollback_from_diff_page():
    username = session.get("username")

    if not username:
        abort(401)

    perms = _user_permissions(username)

    if "write" not in perms:
        abort(403)

    return render_template(
        "rollback_from_diff.html",
        username=username,
        max_limit=10000,
        default_limit=100,
        from_diff_dry_run_only=bool("from_diff_dry_run_only" in perms),
        type="rollback-from-diff",
    )


@app.route("/rollback-account")
def rollback_account_page():
    username = session.get("username")

    if not username:
        abort(401)

    perms = _user_permissions(username)

    if "write" not in perms:
        abort(403)

    return render_template(
        "rollback_account.html",
        username=username,
        max_limit=_ACCOUNT_ROLLBACK_MAX_LIMIT,
        default_limit=_ACCOUNT_ROLLBACK_MAX_LIMIT,
        from_diff_dry_run_only=bool("from_diff_dry_run_only" in perms),
        type="rollback-account",
    )


@app.route("/rollback-requests")
def rollback_requests_page():
    username = session.get("username")

    if not username:
        abort(401)

    can_review = _can_review_requests(username)

    return render_template(
        "rollback_requests.html",
        username=username,
        can_review_all_requests=bool(can_review),
        can_approve_diff=bool(is_maintainer(username)),
        can_approve_batch=bool(can_review),
        type="rollback-requests",
    )


@app.route("/api/v1/rollback/requests", methods=["GET"])
def list_rollback_requests_api():
    username = session.get("username")
    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    can_review = _can_review_requests(username)
    requested_by_filter = request.args.get("requested_by")
    status_filter = request.args.get("status")

    where_parts = ["j.request_type IN (%s, %s)"]
    params = [_REQUEST_TYPE_DIFF, _REQUEST_TYPE_BATCH]

    if status_filter:
        where_parts.append("j.status=%s")
        params.append(status_filter)

    if requested_by_filter:
        if (
            not can_review
            and requested_by_filter.strip().lower() != username.strip().lower()
        ):
            return jsonify({"detail": "Forbidden"}), 403
        where_parts.append("j.requested_by=%s")
        params.append(requested_by_filter)
    elif not can_review:
        where_parts.append("j.requested_by=%s")
        params.append(username)

    where_sql = " AND ".join(where_parts)

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    j.id,
                    j.batch_id,
                    j.requested_by,
                    j.status,
                    j.dry_run,
                    j.created_at,
                    j.request_type,
                    j.requested_endpoint,
                    j.approved_endpoint,
                    j.approval_required,
                    j.approved_by,
                    j.approved_at,
                    COUNT(i.id) AS total_items,
                    COALESCE(SUM(CASE WHEN i.status='completed' THEN 1 ELSE 0 END), 0) AS completed_items,
                    COALESCE(SUM(CASE WHEN i.status='failed' THEN 1 ELSE 0 END), 0) AS failed_items
                FROM rollback_jobs j
                LEFT JOIN rollback_job_items i ON i.job_id = j.id
                WHERE {where_sql}
                GROUP BY
                    j.id,
                    j.batch_id,
                    j.requested_by,
                    j.status,
                    j.dry_run,
                    j.created_at,
                    j.request_type,
                    j.requested_endpoint,
                    j.approved_endpoint,
                    j.approval_required,
                    j.approved_by,
                    j.approved_at
                ORDER BY j.id DESC
                LIMIT 500
                """,
                tuple(params),
            )
            rows = cursor.fetchall()

    requests_payload = []
    for row in rows:
        (
            job_id,
            batch_id,
            requested_by,
            status,
            dry_run,
            created_at,
            request_type,
            requested_endpoint,
            approved_endpoint,
            approval_required,
            approved_by,
            approved_at,
            total,
            completed,
            failed,
        ) = row

        requests_payload.append(
            {
                "id": int(job_id),
                "batch_id": int(batch_id) if batch_id is not None else None,
                "requested_by": requested_by,
                "status": status,
                "dry_run": bool(dry_run),
                "created_at": str(created_at),
                "request_type": request_type,
                "requested_endpoint": requested_endpoint,
                "approved_endpoint": approved_endpoint,
                "approval_required": approval_required,
                "approved_by": approved_by,
                "approved_at": str(approved_at) if approved_at else None,
                "total": int(total or 0),
                "completed": int(completed or 0),
                "failed": int(failed or 0),
            }
        )

    return jsonify(
        {
            "requests": requests_payload,
            "can_review_all_requests": bool(can_review),
            "can_approve_diff": bool(is_maintainer(username)),
            "can_approve_batch": bool(can_review),
        }
    )


@app.route("/api/v1/rollback/requests/<int:job_id>/preview", methods=["GET"])
def rollback_request_preview_api(job_id: int):
    username = session.get("username")
    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    requested_endpoint = _normalize_request_endpoint(request.args.get("endpoint"))
    full_from_diff = _parse_bool(request.args.get("full"), default=True)

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, requested_by, request_type, requested_endpoint
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )
            row = cursor.fetchone()

            if not row:
                return jsonify({"detail": "Request not found"}), 404

            _, requested_by, request_type, stored_endpoint = row

            if requested_by != username and not _can_review_requests(username):
                return jsonify({"detail": "Forbidden"}), 403

            request_type = _normalize_request_type(request_type)

            if request_type == _REQUEST_TYPE_BATCH:
                cursor.execute(
                    """
                    SELECT file_title, target_user, summary, status, error
                    FROM rollback_job_items
                    WHERE job_id=%s
                    ORDER BY id ASC
                    """,
                    (job_id,),
                )
                items = cursor.fetchall()

                preview_items = [
                    {
                        "title": item[0],
                        "user": item[1],
                        "summary": item[2],
                        "status": item[3],
                        "error": item[4],
                    }
                    for item in items
                ]

                return jsonify(
                    {
                        "job_id": job_id,
                        "request_type": request_type,
                        "endpoint": _ENDPOINT_BATCH,
                        "total_items": len(preview_items),
                        "items": preview_items,
                    }
                )

    if request_type != _REQUEST_TYPE_DIFF:
        return jsonify({"detail": f"Unsupported request_type: {request_type}"}), 400

    payload = _load_diff_payload(job_id)
    if not payload:
        return jsonify({"detail": "Missing request payload"}), 404

    endpoint = (
        requested_endpoint
        or _normalize_request_endpoint(
            stored_endpoint or payload.get("requested_endpoint") or _ENDPOINT_FROM_DIFF
        )
    )
    if endpoint not in _ALLOWED_DIFF_REQUEST_ENDPOINTS:
        return jsonify({"detail": "Invalid endpoint"}), 400

    if endpoint == _ENDPOINT_FROM_DIFF and not _request_payload_has_diff_anchor(
        payload
    ):
        return jsonify(
            {
                "detail": "This request does not include a diff anchor for endpoint=from_diff"
            }
        ), 400

    try:
        preview = _compute_diff_request_preview(
            job_id,
            payload,
            endpoint,
            full_from_diff=full_from_diff,
        )
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Failed to compute request preview for job %s", job_id)
        return jsonify({"detail": f"Failed to compute request preview: {exc}"}), 500

    return jsonify(
        {
            "job_id": job_id,
            "request_type": request_type,
            **preview,
        }
    )


@app.route("/rollback-queue/all-jobs")
def rollback_queue_all_jobs_ui():
    username = session.get("username")

    if not username:
        abort(401)

    if "read_all" not in _user_permissions(username) and not is_admin_user(username):
        abort(403)

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    j.id,
                    j.batch_id,
                    j.requested_by,
                    j.status,
                    j.dry_run,
                    j.created_at,
                    j.request_type,
                    j.requested_endpoint,
                    j.approved_endpoint,
                    j.approval_required,
                    j.approved_by,
                    j.approved_at,
                    COUNT(i.id) AS total_items,
                    COALESCE(SUM(CASE WHEN i.status='completed' THEN 1 ELSE 0 END), 0) AS completed_items,
                    COALESCE(SUM(CASE WHEN i.status='failed' THEN 1 ELSE 0 END), 0) AS failed_items
                FROM rollback_jobs j
                LEFT JOIN rollback_job_items i ON i.job_id = j.id
                GROUP BY
                    j.id,
                    j.batch_id,
                    j.requested_by,
                    j.status,
                    j.dry_run,
                    j.created_at,
                    j.request_type,
                    j.requested_endpoint,
                    j.approved_endpoint,
                    j.approval_required,
                    j.approved_by,
                    j.approved_at
                ORDER BY COALESCE(j.batch_id, j.id) DESC, j.id DESC
                """
            )

            jobs = cursor.fetchall()

    if request.args.get("format") == "json":
        jobs_for_output = []
        for row in jobs:
            if len(row) >= 15:
                (
                    job_id,
                    batch_id,
                    requested_by,
                    status,
                    dry_run,
                    created_at,
                    request_type,
                    requested_endpoint,
                    approved_endpoint,
                    approval_required,
                    approved_by,
                    approved_at,
                    total,
                    completed,
                    failed,
                ) = row
            else:
                (
                    job_id,
                    batch_id,
                    requested_by,
                    status,
                    dry_run,
                    created_at,
                    total,
                    completed,
                    failed,
                ) = row
                request_type = None
                requested_endpoint = None
                approved_endpoint = None
                approval_required = None
                approved_by = None
                approved_at = None
            if _maybe_mark_stale_resolving_job_failed(job_id, status, created_at):
                status = "failed"

            # Some legacy rows may store non-numeric batch identifiers.
            # Keep the endpoint resilient by treating unparseable values as null.
            normalized_batch_id = None
            if batch_id is not None:
                try:
                    normalized_batch_id = int(batch_id)
                except (TypeError, ValueError):
                    normalized_batch_id = None

            jobs_for_output.append(
                {
                    "id": job_id,
                    "batch_id": normalized_batch_id,
                    "requested_by": requested_by,
                    "status": status,
                    "dry_run": bool(dry_run),
                    "created_at": str(created_at),
                    "request_type": request_type,
                    "requested_endpoint": requested_endpoint,
                    "approved_endpoint": approved_endpoint,
                    "approval_required": approval_required,
                    "approved_by": approved_by,
                    "approved_at": str(approved_at) if approved_at else None,
                    "total": int(total or 0),
                    "completed": int(completed or 0),
                    "failed": int(failed or 0),
                }
            )

        return jsonify({"jobs": jobs_for_output})

    return render_template(
        "rollback_queue_all_jobs.html",
        jobs=jobs,
        username=username,
        can_approve_diff=bool(is_maintainer(username)),
        can_approve_batch=bool(is_maintainer(username) or is_admin_user(username)),
        type="rollback-all-jobs",
    )


@app.route("/rollback_batch")
def rollback_batch():
    username = session.get("username")

    if not username:
        abort(401)

    if "write" not in _user_permissions(username):
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
            "grant_groups": sorted(_USER_GRANT_GROUPS.keys()),
            "grant_rights": sorted(_USER_GRANT_RIGHTS),
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
            "grant_groups": sorted(_USER_GRANT_GROUPS.keys()),
            "grant_rights": sorted(_USER_GRANT_RIGHTS),
        }
    )


@app.route("/api/v1/config/authz/user-grants/<path:target_username>", methods=["GET"])
def get_runtime_authz_user_grants(target_username: str):
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    if not _can_view_runtime_config(username):
        return jsonify({"detail": "Forbidden"}), 403

    normalized_target = _normalize_username(target_username)
    if not normalized_target:
        return jsonify({"detail": "Username is required"}), 400

    config = _effective_runtime_authz_config()
    payload = _get_user_grants_payload(normalized_target, config)
    payload["implicit_flag_order"] = list(_USER_IMPLICIT_FLAGS)
    payload["grant_groups"] = sorted(_USER_GRANT_GROUPS.keys())
    payload["grant_rights"] = sorted(_USER_GRANT_RIGHTS)
    payload["can_edit"] = _can_edit_runtime_config(username)
    return jsonify(payload)


@app.route("/api/v1/config/authz/user-grants/<path:target_username>", methods=["PUT"])
def update_runtime_authz_user_grants(target_username: str):
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    if not _can_edit_runtime_config(username):
        return jsonify({"detail": "Forbidden"}), 403

    normalized_target = _normalize_username(target_username)
    if not normalized_target:
        return jsonify({"detail": "Username is required"}), 400

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"detail": "Invalid payload"}), 400

    groups = payload.get("groups", [])
    rights = payload.get("rights", [])

    if groups is None:
        groups = []
    if rights is None:
        rights = []

    normalized_entry, errors = _normalize_runtime_authz_updates(
        {
            "USER_GRANTS_JSON": {
                normalized_target: {
                    "groups": groups,
                    "rights": rights,
                }
            }
        }
    )

    if errors:
        return jsonify({"detail": "; ".join(errors)}), 400

    config = _effective_runtime_authz_config()
    grants_map = dict(config.get("USER_GRANTS_JSON") or {})

    user_map = normalized_entry.get("USER_GRANTS_JSON", {})
    if normalized_target in user_map:
        grants_map[normalized_target] = user_map[normalized_target]
    else:
        grants_map.pop(normalized_target, None)

    _persist_runtime_authz_updates(
        {"USER_GRANTS_JSON": grants_map}, updated_by=username
    )
    updated_config = _effective_runtime_authz_config()
    response_payload = _get_user_grants_payload(normalized_target, updated_config)
    response_payload["ok"] = True
    response_payload["can_edit"] = _can_edit_runtime_config(username)
    return jsonify(response_payload)


@app.route("/api/v1/rollback/jobs", methods=["GET"])
def list_rollback_jobs():
    username = session.get("username")
    if username is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    requested_by,
                    status,
                    dry_run,
                    created_at,
                    request_type,
                    requested_endpoint,
                    approved_endpoint,
                    approval_required,
                    approved_by,
                    approved_at
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
                    "request_type": row[5] if len(row) > 5 else None,
                    "requested_endpoint": row[6] if len(row) > 6 else None,
                    "approved_endpoint": row[7] if len(row) > 7 else None,
                    "approval_required": row[8] if len(row) > 8 else None,
                    "approved_by": row[9] if len(row) > 9 else None,
                    "approved_at": (
                        str(row[10]) if len(row) > 10 and row[10] else None
                    ),
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
    request_type = _normalize_request_type(payload.get("request_type"))

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

    requested_endpoint = (
        _ENDPOINT_BATCH if request_type == _REQUEST_TYPE_BATCH else _REQUEST_TYPE_QUEUE
    )
    approval_required = _approval_requirement_for_request(
        request_type, requested_endpoint
    )
    initial_status = (
        _REQUEST_STATUS_PENDING_APPROVAL
        if request_type == _REQUEST_TYPE_BATCH
        else "queued"
    )
    item_initial_status = (
        _REQUEST_STATUS_PENDING_APPROVAL
        if request_type == _REQUEST_TYPE_BATCH
        else "queued"
    )

    job_ids = []

    with get_conn() as conn:
        with conn.cursor() as cursor:
            for i in range(0, len(items), MAX_JOB_ITEMS):
                chunk = items[i : i + MAX_JOB_ITEMS]

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
                        approval_required
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        requested_by,
                        initial_status,
                        1 if dry_run else 0,
                        batch_id,
                        request_type,
                        requested_endpoint,
                        None,
                        approval_required,
                    ),
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
                        (job_id, title, user, summary, item_initial_status),
                    )

        conn.commit()

    if not job_ids:
        return jsonify({"detail": "No valid items to process"}), 400

    if request_type != _REQUEST_TYPE_BATCH:
        for jid in job_ids:
            process_rollback_job.delay(jid)

    return jsonify(
        {
            "job_id": job_ids[0],
            "status": initial_status,
            "batch_id": batch_id,
            "job_ids": job_ids,
            "chunks": len(job_ids),
            "request_type": request_type,
            "requested_endpoint": requested_endpoint,
            "approval_required": approval_required,
        }
    )


@app.route("/api/v1/rollback/jobs/<int:job_id>/approve", methods=["POST"])
def approve_rollback_job(job_id: int):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    endpoint_override = _normalize_request_endpoint(payload.get("endpoint"))

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    requested_by,
                    status,
                    dry_run,
                    batch_id,
                    request_type,
                    requested_endpoint,
                    approved_endpoint,
                    approval_required
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )
            job = cursor.fetchone()

            if not job:
                return jsonify({"detail": "Job not found"}), 404

            (
                _id,
                requested_by,
                status,
                dry_run,
                batch_id,
                request_type,
                requested_endpoint,
                approved_endpoint,
                approval_required,
            ) = job

            request_type = _normalize_request_type(request_type)
            requested_endpoint = _normalize_request_endpoint(requested_endpoint)
            approval_required = approval_required or _approval_requirement_for_request(
                request_type, requested_endpoint
            )

            if not approval_required:
                return jsonify({"detail": "This job does not require approval"}), 400

            if status != _REQUEST_STATUS_PENDING_APPROVAL:
                return jsonify(
                    {"detail": f"Job is not pending approval (status={status})"}
                ), 409

            if not _can_actor_approve(actor, approval_required):
                return jsonify(
                    {"detail": "Forbidden: insufficient approval rights"}
                ), 403

            approved_endpoint = endpoint_override or requested_endpoint

            if request_type == _REQUEST_TYPE_DIFF:
                if approved_endpoint not in _ALLOWED_DIFF_REQUEST_ENDPOINTS:
                    return jsonify(
                        {
                            "detail": (
                                "endpoint must be one of: "
                                + ", ".join(sorted(_ALLOWED_DIFF_REQUEST_ENDPOINTS))
                            )
                        }
                    ), 400

                if approved_endpoint == _ENDPOINT_FROM_DIFF:
                    request_payload = _load_diff_payload(job_id)
                    if not _request_payload_has_diff_anchor(request_payload):
                        return jsonify(
                            {
                                "detail": "This request does not include a diff anchor for endpoint=from_diff"
                            }
                        ), 400

                cursor.execute(
                    """
                    UPDATE rollback_jobs
                    SET
                        status=%s,
                        approved_endpoint=%s,
                        approved_by=%s,
                        approved_at=CURRENT_TIMESTAMP
                    WHERE id=%s
                    """,
                    ("resolving", approved_endpoint, actor, job_id),
                )
                conn.commit()

                _update_diff_payload(
                    job_id,
                    {
                        "approved_endpoint": approved_endpoint,
                        "approved_by": actor,
                        "approved_at": _utc_now_iso(),
                    },
                )
                _set_diff_error(job_id, None)

                status_updater.update_wiki_status(
                    editing="Resolving diff",
                    current_job=f"Approved diff job {job_id} resolving",
                )

                resolve_diff_rollback_job.delay(job_id)

                return jsonify(
                    {
                        "job_id": job_id,
                        "requested_by": requested_by,
                        "approved_by": actor,
                        "approved_endpoint": approved_endpoint,
                        "dry_run": bool(dry_run),
                        "status": "resolving",
                    }
                )

            if request_type != _REQUEST_TYPE_BATCH:
                return jsonify(
                    {"detail": f"Unsupported request_type: {request_type}"}
                ), 400

            if approved_endpoint not in (None, "", _ENDPOINT_BATCH):
                return jsonify(
                    {"detail": "Batch requests can only use endpoint=batch"}
                ), 400

            approved_job_ids = []

            if batch_id is not None:
                cursor.execute(
                    """
                    SELECT id
                    FROM rollback_jobs
                    WHERE batch_id=%s AND request_type=%s AND status=%s
                    ORDER BY id ASC
                    """,
                    (batch_id, _REQUEST_TYPE_BATCH, _REQUEST_STATUS_PENDING_APPROVAL),
                )
                approved_job_ids = [int(row[0]) for row in cursor.fetchall()]

            if not approved_job_ids:
                approved_job_ids = [job_id]

            for approved_job_id in approved_job_ids:
                cursor.execute(
                    """
                    UPDATE rollback_jobs
                    SET
                        status=%s,
                        approved_endpoint=%s,
                        approved_by=%s,
                        approved_at=CURRENT_TIMESTAMP
                    WHERE id=%s
                    """,
                    ("queued", _ENDPOINT_BATCH, actor, approved_job_id),
                )
                cursor.execute(
                    """
                    UPDATE rollback_job_items
                    SET status=%s
                    WHERE job_id=%s AND status=%s
                    """,
                    ("queued", approved_job_id, _REQUEST_STATUS_PENDING_APPROVAL),
                )

        conn.commit()

    status_updater.update_wiki_status(
        editing="Actively editing",
        current_job=f"Processing approved batch job {job_id} with {len(approved_job_ids)} job(s)",
    )

    for approved_job_id in approved_job_ids:
        process_rollback_job.delay(approved_job_id)

    return jsonify(
        {
            "job_id": job_id,
            "batch_id": batch_id,
            "approved_job_ids": approved_job_ids,
            "approved_by": actor,
            "approved_endpoint": _ENDPOINT_BATCH,
            "status": "queued",
        }
    )


@app.route("/api/v1/rollback/jobs/<int:job_id>/reject", methods=["POST"])
def reject_rollback_request(job_id: int):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    requested_by,
                    status,
                    batch_id,
                    request_type,
                    requested_endpoint,
                    approval_required
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )
            row = cursor.fetchone()

            if not row:
                return jsonify({"detail": "Job not found"}), 404

            (
                _id,
                _requested_by,
                status,
                batch_id,
                request_type,
                requested_endpoint,
                approval_required,
            ) = row

            request_type = _normalize_request_type(request_type)
            requested_endpoint = _normalize_request_endpoint(requested_endpoint)
            approval_required = approval_required or _approval_requirement_for_request(
                request_type, requested_endpoint
            )

            if status != _REQUEST_STATUS_PENDING_APPROVAL:
                return jsonify(
                    {"detail": f"Job is not pending approval (status={status})"}
                ), 409

            if not _can_actor_approve(actor, approval_required):
                return jsonify(
                    {"detail": "Forbidden: insufficient approval rights"}
                ), 403

            rejected_job_ids = [job_id]
            if request_type == _REQUEST_TYPE_BATCH and batch_id is not None:
                rejected_job_ids = _pending_batch_request_job_ids(
                    cursor, batch_id, _REQUEST_TYPE_BATCH
                )
                if not rejected_job_ids:
                    rejected_job_ids = [job_id]

            for rejected_job_id in rejected_job_ids:
                cursor.execute(
                    """
                    UPDATE rollback_jobs
                    SET status=%s, approved_by=%s, approved_at=CURRENT_TIMESTAMP
                    WHERE id=%s
                    """,
                    ("canceled", actor, rejected_job_id),
                )
                cursor.execute(
                    """
                    UPDATE rollback_job_items
                    SET status=%s, error=%s
                    WHERE job_id=%s AND status=%s
                    """,
                    (
                        "canceled",
                        "Rejected by approver",
                        rejected_job_id,
                        _REQUEST_STATUS_PENDING_APPROVAL,
                    ),
                )

        conn.commit()

    return jsonify(
        {
            "job_id": job_id,
            "batch_id": batch_id,
            "rejected_job_ids": rejected_job_ids,
            "rejected_by": actor,
            "status": "canceled",
        }
    )


@app.route("/api/v1/rollback/jobs/<int:job_id>/force-dry-run", methods=["POST"])
def force_dry_run_rollback_request(job_id: int):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    status,
                    batch_id,
                    request_type,
                    requested_endpoint,
                    approval_required
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )
            row = cursor.fetchone()

            if not row:
                return jsonify({"detail": "Job not found"}), 404

            (
                _id,
                status,
                batch_id,
                request_type,
                requested_endpoint,
                approval_required,
            ) = row

            request_type = _normalize_request_type(request_type)
            requested_endpoint = _normalize_request_endpoint(requested_endpoint)
            approval_required = approval_required or _approval_requirement_for_request(
                request_type, requested_endpoint
            )

            if status != _REQUEST_STATUS_PENDING_APPROVAL:
                return jsonify(
                    {"detail": f"Job is not pending approval (status={status})"}
                ), 409

            if not _can_actor_approve(actor, approval_required):
                return jsonify(
                    {"detail": "Forbidden: insufficient approval rights"}
                ), 403

            updated_job_ids = [job_id]
            if request_type == _REQUEST_TYPE_BATCH and batch_id is not None:
                updated_job_ids = _pending_batch_request_job_ids(
                    cursor, batch_id, _REQUEST_TYPE_BATCH
                )
                if not updated_job_ids:
                    updated_job_ids = [job_id]

            for updated_job_id in updated_job_ids:
                cursor.execute(
                    "UPDATE rollback_jobs SET dry_run=1 WHERE id=%s",
                    (updated_job_id,),
                )
                if request_type == _REQUEST_TYPE_DIFF:
                    _update_diff_payload(updated_job_id, {"dry_run": True})

        conn.commit()

    return jsonify(
        {
            "job_id": job_id,
            "batch_id": batch_id,
            "updated_job_ids": updated_job_ids,
            "updated_by": actor,
            "dry_run": True,
            "status": _REQUEST_STATUS_PENDING_APPROVAL,
        }
    )


@app.route("/api/v1/rollback/jobs/<int:job_id>/run-live", methods=["POST"])
def run_dry_run_job_live(job_id: int):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    queue_status = "queued"

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    requested_by,
                    status,
                    dry_run,
                    request_type,
                    requested_endpoint,
                    approval_required
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )
            row = cursor.fetchone()

            if not row:
                return jsonify({"detail": "Job not found"}), 404

            (
                requested_by,
                status,
                dry_run,
                request_type,
                requested_endpoint,
                approval_required,
            ) = row

            request_type = _normalize_request_type(request_type)
            requested_endpoint = _normalize_request_endpoint(requested_endpoint)
            approval_required = approval_required or _approval_requirement_for_request(
                request_type, requested_endpoint
            )

            if status != "completed":
                return jsonify(
                    {"detail": f"Job is not completed (status={status})"}
                ), 409

            if not bool(dry_run):
                return jsonify(
                    {"detail": "Job is already configured for live execution"}
                ), 409

            if not _can_run_live(actor, requested_by, approval_required):
                return jsonify({"detail": "Forbidden"}), 403

            cursor.execute(
                "SELECT COUNT(*) FROM rollback_job_items WHERE job_id=%s",
                (job_id,),
            )
            item_count_row = cursor.fetchone()
            item_count = int(item_count_row[0]) if item_count_row else 0

            if item_count == 0 and request_type == _REQUEST_TYPE_DIFF:
                payload = _load_diff_payload(job_id)
                if not payload:
                    return jsonify(
                        {"detail": "Cannot re-run this request without saved payload"}
                    ), 400

                if not _request_payload_has_diff_anchor(payload):
                    return jsonify(
                        {
                            "detail": "Cannot run live from this request because it has no diff anchor"
                        }
                    ), 400

                cursor.execute(
                    "UPDATE rollback_jobs SET dry_run=0, status='resolving' WHERE id=%s",
                    (job_id,),
                )
                conn.commit()

                _update_diff_payload(job_id, {"dry_run": False, "run_live_by": actor})
                _set_diff_error(job_id, None)
                resolve_diff_rollback_job.delay(job_id)
                queue_status = "resolving"
            else:
                cursor.execute(
                    "UPDATE rollback_jobs SET dry_run=0, status='queued' WHERE id=%s",
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
                process_rollback_job.delay(job_id)

    return jsonify(
        {
            "job_id": job_id,
            "status": queue_status,
            "dry_run": False,
            "requested_by": requested_by,
            "run_live_by": actor,
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
                "SELECT requested_by, status, request_type FROM rollback_jobs WHERE id=%s",
                (job_id,),
            )

            job = cursor.fetchone()

            if not job:
                return jsonify({"detail": "Job not found"}), 404

            if job[0] != actor:
                if "retry_any" not in _user_permissions(actor):
                    return jsonify({"detail": "Forbidden"}), 403

            current_status = str(job[1] or "") if len(job) > 1 else ""
            request_type = (
                _normalize_request_type(job[2]) if len(job) > 2 else _REQUEST_TYPE_QUEUE
            )

            if current_status == _REQUEST_STATUS_PENDING_APPROVAL:
                return jsonify(
                    {
                        "detail": "This request is pending approval and cannot be retried yet"
                    }
                ), 409

            cursor.execute(
                "SELECT COUNT(*) FROM rollback_job_items WHERE job_id=%s",
                (job_id,),
            )
            item_count_row = cursor.fetchone()
            item_count = int(item_count_row[0]) if item_count_row else 0

            if item_count == 0:
                payload = _load_diff_payload(job_id)
                if not payload:
                    return jsonify(
                        {"detail": "Cannot retry this job without saved diff payload"}
                    ), 400

                if (
                    request_type == _REQUEST_TYPE_DIFF
                    and current_status == _REQUEST_STATUS_PENDING_APPROVAL
                ):
                    return jsonify(
                        {"detail": "Diff request is still pending approval"}
                    ), 409

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
                        return jsonify(
                            {
                                "detail": "Forbidden: canceling a bot-admin's job requires bot-admin rights"
                            }
                        ), 403
                elif is_maintainer(job_owner):
                    # Regular maintainer's job: any maintainer (or bot admin) may cancel it.
                    if not is_maintainer(actor):
                        return jsonify(
                            {
                                "detail": "Forbidden: canceling a maintainer's job requires maintainer rights"
                            }
                        ), 403
                elif is_admin_user(job_owner):
                    # Admin job: any maintainer (or bot admin) may cancel it.
                    if "cancel_admin_jobs" not in actor_perms:
                        return jsonify(
                            {
                                "detail": "Forbidden: canceling an admin's job requires maintainer rights"
                            }
                        ), 403
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
                WHERE job_id=%s AND status IN (%s, %s, %s, %s, %s)
                """,
                (
                    "canceled",
                    "Canceled by requester",
                    job_id,
                    "queued",
                    "running",
                    "resolving",
                    "staging",
                    _REQUEST_STATUS_PENDING_APPROVAL,
                ),
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
                SELECT
                    id,
                    requested_by,
                    status,
                    dry_run,
                    created_at,
                    request_type,
                    requested_endpoint,
                    approved_endpoint,
                    approval_required,
                    approved_by,
                    approved_at
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
        if len(job) >= 11:
            job = (
                job[0],
                job[1],
                "failed",
                job[3],
                job[4],
                job[5],
                job[6],
                job[7],
                job[8],
                job[9],
                job[10],
            )
        else:
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
            "request_type": job[5] if len(job) > 5 else None,
            "requested_endpoint": job[6] if len(job) > 6 else None,
            "approved_endpoint": job[7] if len(job) > 7 else None,
            "approval_required": job[8] if len(job) > 8 else None,
            "approved_by": job[9] if len(job) > 9 else None,
            "approved_at": (str(job[10]) if len(job) > 10 and job[10] else None),
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
