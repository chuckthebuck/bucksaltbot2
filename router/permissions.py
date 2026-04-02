"""User permission checking functions."""

import sys as _sys
import time


from app import flask_app as app, is_maintainer
from redis_state import r
from router.framework_config import RATE_LIMIT_KEY_PREFIX
from router.authz import (
    ALLOWED_GROUPS,
    is_bot_admin,
    _effective_runtime_authz_config,
    _expand_all_grants,
    _normalize_grant_atom,
    _USER_GRANT_RIGHTS,
    _CONFIG_EDIT_PRIMARY_ACCOUNT,
    get_user_groups,
)


def _r():
    """Return the router package module (supports test-side patching via router.X)."""
    return _sys.modules.get("router")


def is_authorized(username):
    if not username:
        return False

    _router = _r()
    _is_maintainer = _router.is_maintainer if _router else is_maintainer
    _erc = (
        _router._effective_runtime_authz_config
        if _router
        else _effective_runtime_authz_config
    )
    config = _erc()

    if _is_maintainer(username):
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
    _router = _r()
    _is_bot_admin = _router.is_bot_admin if _router else is_bot_admin
    _is_maintainer = _router.is_maintainer if _router else is_maintainer
    if _is_bot_admin(username):
        return True

    if _is_maintainer(username):
        return True

    config = _effective_runtime_authz_config()
    grants = _expand_all_grants(config, username)
    return "edit_config" in grants or "manage_user_grants" in grants


def _can_edit_runtime_config(username: str) -> bool:
    if not username:
        return False
    _router = _r()
    _is_bot_admin = _router.is_bot_admin if _router else is_bot_admin
    return (
        _is_bot_admin(username)
        and username.strip().lower() == _CONFIG_EDIT_PRIMARY_ACCOUNT
    ) or _user_has_grant_right(username, "edit_config")


def _can_manage_user_grants(username: str) -> bool:
    if not username:
        return False
    _router = _r()
    _is_bot_admin = _router.is_bot_admin if _router else is_bot_admin
    if _is_bot_admin(username):
        return True

    return _user_has_grant_right(username, "manage_user_grants")


def _user_has_grant_right(username: str, right: str) -> bool:
    normalized_right = _normalize_grant_atom(right)
    if normalized_right not in _USER_GRANT_RIGHTS:
        return False

    config = _effective_runtime_authz_config()
    grants = _expand_all_grants(config, username)
    return normalized_right in grants


def is_tester(username: str) -> bool:
    """Return True if the user is in the USERS_TESTER env-var list.

    Testers sit between regular users and maintainers: they have rollback
    access plus read-all and a higher rate limit, but no
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

    Permission strings (canonical)
    ------------------------------
    read_own                     — view the user's own jobs
    write                        — submit baseline queue rollback jobs
    cancel_own                   — cancel the user's own jobs
    retry_own                    — retry the user's own jobs
    view_all                     — view every user's jobs (all-jobs interface)
    rollback_diff                — submit diff-based rollback requests
    rollback_account             — submit account-based rollback requests
    rollback_batch               — submit batch rollback requests
    rollback_diff_dry_run_only   — diff/account rollback access is dry-run only
    approve_jobs                 — approve/reject pending requests
    autoapprove_jobs             — auto-approve requests in test mode when enabled
    force_dry_run                — force pending requests into dry-run mode
    cancel_any                   — cancel any non-privileged (regular) user's job
    retry_any                    — retry any user's job
    edit_config                  — edit runtime config
    manage_user_grants           — manage user-grant atoms in runtime config
    cancel_admin_jobs            — cancel a Commons admin (sysop) user's job; all maintainers
    cancel_maintainer_jobs       — cancel a maintainer's job; only bot admins possess this
    config_view                  — view runtime config editor/API
    config_edit                  — edit runtime config API

    Compatibility aliases are also emitted for legacy checks/UI:
    read_all, from_diff, from_diff_dry_run_only, batch.
    """
    if not username:
        return frozenset()

    _router = _r()
    _is_maintainer = _router.is_maintainer if _router else is_maintainer
    _is_bot_admin = _router.is_bot_admin if _router else is_bot_admin
    _is_tester = _router.is_tester if _router else is_tester
    _erc = (
        _router._effective_runtime_authz_config
        if _router
        else _effective_runtime_authz_config
    )

    lower = username.lower()
    config = _erc()

    # Read-only users may only view their own jobs.
    if lower in config["USERS_READ_ONLY"]:
        return frozenset({"read_own"})

    # Base permissions granted to every authenticated user.
    perms: set = {"read_own", "write", "cancel_own", "retry_own"}

    if _is_maintainer(username):
        # Maintainers are above admins: they can cancel any admin's job.
        perms |= {
            "view_all",
            "rollback_diff",
            "rollback_account",
            "rollback_batch",
            "approve_jobs",
            "autoapprove_jobs",
            "force_dry_run",
            "cancel_any",
            "retry_any",
            "edit_config",
            "manage_user_grants",
            "cancel_admin_jobs",
        }
        # Bot admins (chuckbot) sit above all maintainers and can cancel their jobs too.
        if _is_bot_admin(username):
            perms.add("cancel_maintainer_jobs")
    elif _is_tester(username):
        # Testers get rollback access but no cross-user actions.
        perms |= {
            "view_all",
            "rollback_diff",
            "rollback_account",
            "rollback_batch",
        }
    else:
        # Legacy per-right grants for non-maintainer, non-tester accounts.
        if lower in config["USERS_GRANTED_FROM_DIFF"]:
            perms |= {"rollback_diff", "rollback_account"}
        if lower in config["USERS_GRANTED_VIEW_ALL"]:
            perms.add("view_all")
        if lower in config["USERS_GRANTED_BATCH"]:
            perms.add("rollback_batch")
        if lower in config["USERS_GRANTED_CANCEL_ANY"]:
            perms.add("cancel_any")
        if lower in config["USERS_GRANTED_RETRY_ANY"]:
            perms.add("retry_any")

        # User-centric grants (MediaWiki-style): username -> rights/groups.
        expanded_grants = _expand_all_grants(config, lower)
        if "rollback_diff_dry_run_only" in expanded_grants:
            # Dry-run-only implies diff/account rollback access.
            perms |= {
                "rollback_diff",
                "rollback_account",
                "rollback_diff_dry_run_only",
            }
        if "rollback_diff" in expanded_grants:
            perms.add("rollback_diff")
        if "rollback_account" in expanded_grants:
            perms.add("rollback_account")
        if "view_all" in expanded_grants:
            perms.add("view_all")
        if "rollback_batch" in expanded_grants:
            perms.add("rollback_batch")
        if "approve_jobs" in expanded_grants:
            perms.add("approve_jobs")
        if "autoapprove_jobs" in expanded_grants:
            perms.add("autoapprove_jobs")
        if "force_dry_run" in expanded_grants:
            perms.add("force_dry_run")
        if "edit_config" in expanded_grants:
            perms.add("edit_config")
        if "manage_user_grants" in expanded_grants:
            perms.add("manage_user_grants")
        if "cancel_any" in expanded_grants:
            perms.add("cancel_any")
        if "retry_any" in expanded_grants:
            perms.add("retry_any")

    perms |= _expand_all_grants(config, lower)

    if "rollback_diff_dry_run_only" in perms:
        perms |= {"rollback_diff", "rollback_account"}

    # Compatibility aliases for existing checks/UI.
    if "view_all" in perms:
        perms.add("read_all")
    if "rollback_diff" in perms:
        perms.add("from_diff")
    if "rollback_batch" in perms:
        perms.add("batch")
    if "rollback_diff_dry_run_only" in perms:
        perms.add("from_diff_dry_run_only")

    if _can_view_runtime_config(username):
        perms.add("config_view")

    if _can_edit_runtime_config(username):
        perms |= {"config_edit", "edit_config"}

    if _can_manage_user_grants(username):
        perms.add("manage_user_grants")

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
    _router = _r()
    _is_maintainer = _router.is_maintainer if _router else is_maintainer
    if _is_maintainer(username):
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
    key = f"{RATE_LIMIT_KEY_PREFIX}:{username.lower()}:{hour_bucket}"

    _router = _r()
    _redis = _router.r if _router else r
    try:
        count = _redis.incr(key)
        if count == 1:
            # First entry in this bucket — expire after two hours for cleanup.
            _redis.expire(key, 7200)
        return int(count) <= limit
    except Exception:
        app.logger.warning("Rate-limit check failed for %s; failing open.", username)
        return True
