"""Permission checks: authorization, user groups, rate limiting."""

import time

import requests

from app import flask_app as app, is_maintainer
from redis_state import r
from router.authz import (
    ALLOWED_GROUPS,
    GROUP_CACHE_TTL,
    _CONFIG_EDIT_PRIMARY_ACCOUNT,
    _effective_runtime_authz_config,
    _expand_user_grants,
    _group_cache,
    is_bot_admin,
)


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


def _can_view_runtime_config(username: str) -> bool:
    if not username:
        return False
    return is_bot_admin(username)


def _can_edit_runtime_config(username: str) -> bool:
    if not username:
        return False
    return is_bot_admin(username) and username.strip().lower() == _CONFIG_EDIT_PRIMARY_ACCOUNT


def is_tester(username: str) -> bool:
    """Return True if the user is in the USERS_TESTER env-var list."""
    if not username:
        return False
    config = _effective_runtime_authz_config()
    return username.strip().lower() in config["USERS_TESTER"]


def _user_permissions(username: str) -> frozenset:
    """Return the set of permission flags for an already-authenticated user."""
    if not username:
        return frozenset()

    lower = username.lower()
    config = _effective_runtime_authz_config()

    if lower in config["USERS_READ_ONLY"]:
        return frozenset({"read_own"})

    perms: set = {"read_own", "write", "cancel_own", "retry_own"}

    if is_maintainer(username):
        perms |= {"read_all", "from_diff", "batch", "cancel_any", "retry_any", "cancel_admin_jobs"}
        if is_bot_admin(username):
            perms.add("cancel_maintainer_jobs")
    elif is_tester(username):
        perms |= {"read_all", "from_diff", "batch"}
    else:
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

        expanded_grants = _expand_user_grants(config, lower)
        if "from_diff_dry_run_only" in expanded_grants:
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
    """Return True if the user is within their per-hour job-creation rate limit."""
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
            r.expire(key, 7200)
        return int(count) <= limit
    except Exception:
        app.logger.warning(
            "Rate-limit check failed for %s; failing open.", username
        )
        return True
