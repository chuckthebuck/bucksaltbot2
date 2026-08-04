"""Convert authenticated usernames and policy grants into framework permissions.

Admission and permission callers supply a session-authenticated username; a
non-empty string is not proof of identity.  Classification helpers may inspect
other usernames, but do not authenticate them.  This layer applies the framework
hierarchy on top of the normalized policy assembled by :mod:`router.authz`:
maintainers receive fixed operational powers, regular users receive expanded
direct/role grants, and the explicit built-in ``read_only`` group overrides
positive grants for regular users.  Empty identities, unknown rights, and missing
role data deny access.

The Redis job-rate limiter lives here because it gates the same submission path,
but it is not an authorization source.  It deliberately fails open during a
Redis outage after the caller has passed normal authentication and permission
checks.
"""

import sys as _sys
import time


from app import flask_app as app, is_maintainer
from redis_state import r
from router.framework_config import RATE_LIMIT_KEY_PREFIX
from router.authz import (
    is_bot_admin,
    _effective_runtime_authz_config,
    _expand_all_grants,
    _normalize_grant_atom,
    _USER_GRANT_RIGHTS,
    _USER_GRANT_GROUPS,
    _CONFIG_EDIT_PRIMARY_ACCOUNT,
    get_user_groups,
)


def _r():
    """Return the package facade used by legacy imports and test patch points.

    Several dependencies are re-exported from ``router.__init__``.  Resolving
    those selected values dynamically retains compatibility with existing
    deployments and tests that replace ``router.X`` rather than this submodule.
    """
    return _sys.modules.get("router")


def is_authorized(username):
    """Return whether an authenticated identity may enter the application.

    Maintainers bypass runtime admission policy.  Everyone else needs at least
    one enforceable direct or implicit-role right; an empty/unknown username or a
    grant group that expands to no rights is denied.  This function does not
    authenticate the supplied username.
    """
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
        # Maintainer membership is the framework's trusted operational override
        # and therefore does not depend on mutable runtime grant rows.
        return True

    # bool(set) intentionally fails closed for unknown users, unresolved custom
    # groups, and failed Wikimedia membership lookups.
    return bool(_expand_all_grants(config, username))


def is_admin_user(username: str) -> bool:
    """Return whether a user is currently a Commons ``sysop``.

    This classifies job owners for cancellation policy; it is distinct from an
    application bot admin or maintainer.  Remote lookup failures yield no groups,
    so the check itself fails closed.
    """
    if not username:
        return False
    return "sysop" in get_user_groups(username)


def _can_view_runtime_config(username: str) -> bool:
    """Return whether an identity may inspect runtime authorization policy.

    Bot admins and maintainers may always inspect it.  Other users need either
    the ``edit_config`` or ``manage_user_grants`` configured right.  Empty users
    and unavailable role membership resolve to denial.
    """
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
    """Return whether an identity may change the general runtime policy map.

    The configured primary bot account has a dedicated administrative path.
    Separately, policy may delegate ``edit_config`` explicitly to another user or
    role.  Merely being a bot admin or maintainer is not enough unless one of
    those two conditions applies.
    """
    if not username:
        return False
    _router = _r()
    _is_bot_admin = _router.is_bot_admin if _router else is_bot_admin
    return (
        _is_bot_admin(username)
        and username.strip().lower() == _CONFIG_EDIT_PRIMARY_ACCOUNT
    ) or _user_has_grant_right(username, "edit_config")


def _can_manage_user_grants(username: str) -> bool:
    """Return whether an identity may assign per-user grant atoms.

    Every bot admin has this capability; other identities need the explicit
    ``manage_user_grants`` right.  This separation lets policy editing and user
    assignment be delegated independently.
    """
    if not username:
        return False
    _router = _r()
    _is_bot_admin = _router.is_bot_admin if _router else is_bot_admin
    if _is_bot_admin(username):
        return True

    return _user_has_grant_right(username, "manage_user_grants")


def _user_has_grant_right(username: str, right: str) -> bool:
    """Check one canonical application-wide right against expanded policy.

    The allowlist check happens before expansion, so typos and module-scoped
    atoms cannot be smuggled through this generic helper.
    """
    normalized_right = _normalize_grant_atom(right)
    if normalized_right not in _USER_GRANT_RIGHTS:
        return False

    config = _effective_runtime_authz_config()
    grants = _expand_all_grants(config, username)
    return normalized_right in grants


def is_tester(username: str) -> bool:
    """Return whether the user is directly assigned the built-in tester group.

    This deliberately checks the stored group atom rather than an equivalent set
    of expanded rights: the label selects the tester-specific rate-limit tier.
    Auto grants and unrelated custom groups therefore do not make someone a
    tester implicitly.
    """
    if not username:
        return False
    config = _effective_runtime_authz_config()
    grants_map = config.get("ROLLBACK_CONTROL_JSON") or {}
    atoms = grants_map.get(username.strip().lower()) or []
    return "group:tester" in {_normalize_grant_atom(atom) for atom in atoms}


def _user_permissions(username: str) -> frozenset:
    """Return the set of permission flags for an already-authenticated user.

    Policy precedence (highest → lowest)
    -------------------------------------
    bot-admin addition             — may also cancel maintainers' jobs
    maintainer powers              — fixed framework operational capabilities
    built-in read_only group       — strips regular users back to read_own
    explicit user grants           — rights/groups in ROLLBACK_CONTROL_JSON
    implicit role grants           — configured Wikimedia project/global groups

    The bot-admin addition is evaluated inside the maintainer branch because bot
    admins are expected to be maintainers.  Direct and role grants are otherwise
    additive.  The ``read_only`` group is the one deny-style exception and wins
    over all positive runtime grants for non-maintainers.

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
    estop_rollback               — trigger the rollback emergency stop
    approve_jobs                 — approve/reject pending requests
    autoapprove_jobs             — auto-approve requests in test mode when enabled
    force_dry_run                — force pending requests into dry-run mode
    cancel_any                   — cancel any non-privileged (regular) user's job
    retry_any                    — retry any user's job
    edit_config                  — configured general-config edit marker
    manage_user_grants           — configured user-grant management marker
    manage_modules               — administer modules across the framework
    run_module_jobs              — run jobs for modules across the framework
    edit_module_config           — edit configuration across modules
    module:<module>:<right>       — a module-scoped configured capability
    cancel_admin_jobs            — cancel a Commons admin's job; maintainers only
    cancel_maintainer_jobs       — cancel a maintainer's job; bot admins only
    config_view                  — view runtime config editor/API
    config_edit                  — edit runtime config API

    Compatibility aliases are also emitted for legacy checks/UI:
    read_all, from_diff, from_diff_dry_run_only, batch.

    Runtime-config routes enforce :func:`_can_view_runtime_config`,
    :func:`_can_edit_runtime_config`, and :func:`_can_manage_user_grants`
    directly.  ``config_view`` and ``config_edit`` expose the first two effective
    outcomes to callers; raw grant markers are not a substitute for route checks.
    """
    if not username:
        return frozenset()

    _router = _r()
    _is_maintainer = _router.is_maintainer if _router else is_maintainer
    _is_bot_admin = _router.is_bot_admin if _router else is_bot_admin
    _erc = (
        _router._effective_runtime_authz_config
        if _router
        else _effective_runtime_authz_config
    )

    # Legacy framework-wide grant lookup lowercases the complete session name
    # before first-letter normalization. This cannot distinguish MediaWiki
    # usernames that differ only by later capitalization; module-right helpers
    # that receive the original username do not share this exact lookup path.
    lower = username.lower()
    config = _erc()

    # Authentication alone gives ownership-scoped visibility.  Mutation powers
    # are derived below and never implied by a non-empty username.
    perms: set = {"read_own"}

    if _is_maintainer(username):
        # Maintainers are above admins: they can cancel any admin's job.
        perms |= {
            "write",
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
            "manage_modules",
            "run_module_jobs",
            "edit_module_config",
            "cancel_admin_jobs",
        }
        # Bot admins (chuckbot) sit above all maintainers and can cancel their jobs too.
        if _is_bot_admin(username):
            perms.add("cancel_maintainer_jobs")
    else:
        expanded_grants = _expand_all_grants(config, lower)
        # read_only is a policy override, not an empty grant bundle: returning
        # early prevents explicit or auto-granted rights from re-enabling writes.
        if "read_only" in _user_group_atoms(config, lower):
            return frozenset({"read_own"})
        perms |= expanded_grants

    if "write" in perms:
        # Submission access entails control of one's own resulting jobs, but not
        # anyone else's jobs.
        perms |= {"cancel_own", "retry_own"}

    if "rollback_diff_dry_run_only" in perms:
        # The restriction is checked by rollback routes.  These positive rights
        # still expose the relevant UI/API entry points for dry-run submissions.
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

    # Config-facing flags are derived through their dedicated policy checks so
    # the UI and API share exactly the same view/edit boundary.
    if _can_view_runtime_config(username):
        perms.add("config_view")

    if _can_edit_runtime_config(username):
        perms |= {"config_edit", "edit_config"}

    if _can_manage_user_grants(username):
        perms.add("manage_user_grants")

    return frozenset(perms)


def _user_group_atoms(config: dict, username: str) -> set[str]:
    """Return recognized built-in group labels directly assigned to a user.

    This intentionally does not expand aliases, custom groups, or role grants.
    It exists for label-sensitive policy such as the deny-style ``read_only``
    override, where an equivalent bundle of positive rights is not sufficient.
    """
    atoms = set()
    grants_map = config.get("ROLLBACK_CONTROL_JSON") or {}
    for atom in grants_map.get(username.strip().lower(), []):
        normalized = _normalize_grant_atom(atom)
        if normalized.startswith("group:"):
            group_name = normalized.split(":", 1)[1]
            if group_name in _USER_GRANT_GROUPS:
                atoms.add(group_name)
    return atoms


def _check_rate_limit(username: str) -> bool:
    """Return True if the user is within their per-hour job-creation rate limit.

    Tiers
    -----
    maintainer  — never rate-limited.
    tester      — checked against RATE_LIMIT_TESTER_JOBS_PER_HOUR (falls back to
                  RATE_LIMIT_JOBS_PER_HOUR when unset).
    regular     — checked against RATE_LIMIT_JOBS_PER_HOUR.

    When the applicable limit is 0, rate limiting is disabled for that tier.  A
    Redis ``INCR`` gives each lowercase username an atomic fixed-window counter
    keyed by Unix-epoch hour.  The first increment attaches a two-hour cleanup
    TTL, long enough to outlive the active window.

    Redis errors fail open so a state-service outage does not block otherwise
    authorized job submission.  Authentication and ``write`` authorization must
    therefore be checked independently before this helper is called.
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
    # Lowercasing avoids giving one authenticated identity parallel counters via
    # presentation-case variants.
    key = f"{RATE_LIMIT_KEY_PREFIX}:{username.lower()}:{hour_bucket}"

    _router = _r()
    _redis = _router.r if _router else r
    try:
        # INCR is atomic in Redis, so concurrent submissions cannot all observe
        # the same pre-increment count.
        count = _redis.incr(key)
        if count == 1:
            # First entry in this bucket — expire after two hours for cleanup.
            _redis.expire(key, 7200)
        return int(count) <= limit
    except Exception:
        app.logger.warning("Rate-limit check failed for %s; failing open.", username)
        return True
