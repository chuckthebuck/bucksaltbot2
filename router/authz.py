"""Build and resolve the framework's authorization configuration.

This module is the policy-data layer, not an authentication layer.  Enforcement
callers must pass identities established by the application; inspection helpers
may instead receive an administrator-selected target username.  The module:

* turns environment variables into a backwards-compatible baseline;
* overlays normalized, persisted runtime configuration on that baseline;
* expands direct user grants and Wikimedia-backed role grants into rights; and
* caches runtime configuration and remote Wikimedia group lookups briefly.

Runtime JSON is treated as untrusted even though only privileged users can edit
it.  Unknown application-wide rights and malformed selectors never become
permissions; syntactically valid module-scoped rights remain extensible by
design.  Failed Wikimedia lookups produce an empty group set, so remote-role
authorization fails closed.  Legacy grant names remain accepted because existing
database rows may contain them, but aliases are resolved only while evaluating
policy so an admin can still inspect the exact stored value.
"""

import json
import os
import time

import sys as _sys

import requests

from http_config import http_headers
from app import BOT_ADMIN_ACCOUNTS, flask_app as app, is_maintainer  # noqa: F401
from router.framework_config import (
    ALLOWED_GROUPS as FRAMEWORK_ALLOWED_GROUPS,
    WIKI_API_URL,
)
from toolsdb import get_runtime_config, upsert_runtime_config


def _r():
    """Return the package facade used by legacy imports and test patch points.

    ``router.__init__`` re-exports these helpers.  Looking up selected dependencies
    there preserves the historic ``patch("router.X")`` behavior while allowing
    this implementation to live in a dedicated module.
    """
    return _sys.modules.get("router")


# Remote membership data is process-local and deliberately short-lived.  The
# cache contains both successful and empty results; caching an empty result keeps
# a Wikimedia outage from causing a request storm without granting any privilege.
GROUP_CACHE_TTL = 300
_group_cache: dict = {}
# Re-exported for callers that still import the framework setting from authz.
ALLOWED_GROUPS = FRAMEWORK_ALLOWED_GROUPS


def _env_user_set(env_var: str) -> set[str]:
    """Read a legacy comma-separated username set from the process environment.

    These sets are loaded once at import time and later converted into current
    ``ROLLBACK_CONTROL_JSON`` group atoms by :func:`_runtime_authz_defaults`.
    """
    return {u.strip().lower() for u in os.getenv(env_var, "").split(",") if u.strip()}


EXTRA_AUTHORIZED_USERS: set[str] = _env_user_set("EXTRA_AUTHORIZED_USERS")
USERS_READ_ONLY: set[str] = _env_user_set("USERS_READ_ONLY")
USERS_TESTER: set[str] = _env_user_set("USERS_TESTER")
USERS_GRANTED_FROM_DIFF: set[str] = _env_user_set("USERS_GRANTED_FROM_DIFF")
USERS_GRANTED_VIEW_ALL: set[str] = _env_user_set("USERS_GRANTED_VIEW_ALL")
USERS_GRANTED_BATCH: set[str] = _env_user_set("USERS_GRANTED_BATCH")
USERS_GRANTED_CANCEL_ANY: set[str] = _env_user_set("USERS_GRANTED_CANCEL_ANY")
USERS_GRANTED_RETRY_ANY: set[str] = _env_user_set("USERS_GRANTED_RETRY_ANY")

RATE_LIMIT_JOBS_PER_HOUR: int = int(os.getenv("RATE_LIMIT_JOBS_PER_HOUR", "0"))
RATE_LIMIT_TESTER_JOBS_PER_HOUR: int = int(
    os.getenv("RATE_LIMIT_TESTER_JOBS_PER_HOUR", str(RATE_LIMIT_JOBS_PER_HOUR))
)

_CONFIG_EDIT_PRIMARY_ACCOUNT = (
    os.getenv("CONFIG_EDIT_PRIMARY_ACCOUNT", "chuckbot").strip().lower()
)

# Canonical application-wide rights accepted in direct and group grants.  Module
# rights use the separate ``module:<id>:<right>`` namespace.
_USER_GRANT_RIGHTS = {
    "write",
    "rollback_diff",
    "rollback_account",
    "rollback_batch",
    "rollback_diff_dry_run_only",
    "estop_rollback",
    "approve_jobs",
    "autoapprove_jobs",
    "force_dry_run",
    "view_all",
    "edit_config",
    "manage_user_grants",
    "cancel_any",
    "retry_any",
    "manage_modules",
    "run_module_jobs",
    "edit_module_config",
}

# Vocabulary for the framework's built-in module actions.  Atom validation stays
# intentionally permissive so independently deployed modules can add rights.
_MODULE_BUILTIN_RIGHTS = {
    "access",
    "view",
    "estop",
    "manage",
    "view_jobs",
    "run_jobs",
    "edit_config",
}

_USER_GRANT_GROUPS = {
    # These named groups are the human-facing access bundles used by both
    # runtime config and legacy env var migration.
    "basic": {"write"},
    "read_only": set(),
    "tester": {
        "write",
        "view_all",
        "rollback_diff",
        "rollback_account",
        "rollback_batch",
    },
    "viewer": {"view_all"},
    "rollbacker": {"write", "rollback_diff", "rollback_account"},
    "rollbacker_dry_run": {
        "write",
        "rollback_diff",
        "rollback_account",
        "rollback_diff_dry_run_only",
    },
    "batch_runner": {"write", "rollback_batch"},
    "jobs_moderator": {
        "approve_jobs",
        "force_dry_run",
        "cancel_any",
        "retry_any",
    },
    "config_editor": {"edit_config"},
    "rights_manager": {"manage_user_grants"},
    "module_operator": {"manage_modules", "run_module_jobs", "edit_module_config"},
    "admin": {
        "write",
        "view_all",
        "rollback_diff",
        "rollback_account",
        "rollback_batch",
        "estop_rollback",
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
    },
}

_LEGACY_RIGHT_ALIASES = {
    # Keep accepting old grant names so previously persisted config continues
    # to behave the same after the granular-permission migration.
    "from_diff": "rollback_diff",
    "batch": "rollback_batch",
    "from_diff_dry_run_only": "rollback_diff_dry_run_only",
    "read_all": "view_all",
}

_LEGACY_GROUP_ALIASES = {
    "diff": "rollbacker",
    "diff_dry_run": "rollbacker_dry_run",
    "batch": "batch_runner",
    "support": "jobs_moderator",
    "operator": "admin",
}

# Built-in role labels reported by the grants-inspection API.  Project and global
# selectors are discovered dynamically from ROLE_GRANTS_JSON as well.
_USER_IMPLICIT_FLAGS = (
    "authenticated",
    "commons_admin",
    "commons_rollbacker",
)

_AUTO_GRANT_ROLE_KEYS = set(_USER_IMPLICIT_FLAGS)

# These Wikimedia roles are intrinsic admission sources for the vendored
# Temporary Account Finder. They grant only the ability to enter that module;
# every lookup still checks the OAuth user's effective reveal right and block
# state on the selected wiki. Keeping these atoms mandatory also prevents an
# older persisted ROLE_GRANTS_JSON row from accidentally removing TAIV access.
_REQUIRED_ROLE_GRANTS = {
    "global:global-temporary-account-viewer": {
        "module:temporary_account_finder:view"
    },
    "project:commons:temporary-account-viewer": {
        "module:temporary_account_finder:view"
    },
    "project:enwiki:temporary-account-viewer": {
        "module:temporary_account_finder:view"
    },
    "project:meta:temporary-account-viewer": {
        "module:temporary_account_finder:view"
    },
}

# These keys are read for migration only.  New writes use the JSON policy maps.
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
    "ROLLBACK_CONTROL_JSON",
    "ROLE_GRANTS_JSON",
    "CHUCKBOT_GROUPS_JSON",
    "CHUCKBOT_GROUP_DESCRIPTIONS_JSON",
}

_LEGACY_JSON_CONFIG_KEYS = {
    "USER_GRANTS_JSON",
    "AUTO_GRANTS_JSON",
}

# Only current integer and JSON keys may be written through the runtime API.
_RUNTIME_AUTHZ_ALLOWED_KEYS = sorted(_INT_CONFIG_KEYS | _JSON_CONFIG_KEYS)
# Runtime database reads are cached per process; a successful local write clears
# this cache immediately, while writes made by another process converge by TTL.
_RUNTIME_AUTHZ_CACHE_TTL = 60
_runtime_authz_cache = None
_runtime_authz_cache_expiry = 0.0


def _parse_user_csv(raw_value: str) -> set[str]:
    """Parse a persisted legacy username list for one-time policy migration."""
    return {u.strip().lower() for u in (raw_value or "").split(",") if u.strip()}


def _normalize_username(raw_value: str) -> str:
    """Normalize a username to MediaWiki's first-letter-uppercase display shape.

    Underscores and repeated whitespace are normalized, and copy/pasted ``User:``
    prefixes or matching quotes are removed.  Only the first character's case is
    changed: the rest must be preserved because MediaWiki usernames that differ
    later in the string can identify different accounts.
    """
    cleaned = str(raw_value or "").strip()

    if cleaned.lower().startswith("user:"):
        cleaned = cleaned[5:].strip()

    if len(cleaned) >= 2 and (
        (cleaned[0] == '"' and cleaned[-1] == '"')
        or (cleaned[0] == "'" and cleaned[-1] == "'")
    ):
        cleaned = cleaned[1:-1].strip()

    cleaned = " ".join(cleaned.replace("_", " ").split())
    if not cleaned:
        return ""
    return cleaned[0].upper() + cleaned[1:]


def _normalize_auto_grant_role_name(raw_value: str) -> str:
    """Normalize an implicit-role selector without erasing its scope syntax.

    Historical Commons spellings collapse to the built-in names; generic
    ``project:<wiki>:<group>`` and ``global:<group>`` selectors pass through for
    structural validation by :func:`_is_valid_auto_grant_role`.
    """
    value = str(raw_value or "").strip().lower().replace(" ", "_")
    if value in {"commons_admin", "project:commons:sysop"}:
        return "commons_admin"
    if value in {"commons_rollbacker", "project:commons:rollbacker"}:
        return "commons_rollbacker"
    return value


def _is_valid_auto_grant_role(role_name: str) -> bool:
    """Return whether a role name is a supported, non-empty selector shape.

    This validates syntax only.  Membership is resolved against Wikimedia when
    policy is expanded; unrecognized shapes return ``False`` (fail closed).
    """
    role_name = _normalize_auto_grant_role_name(role_name)
    if role_name in _AUTO_GRANT_ROLE_KEYS:
        return True
    parts = role_name.split(":")
    if len(parts) == 2 and parts[0] == "global" and bool(parts[1]):
        return True
    if len(parts) == 3 and parts[0] == "project" and bool(parts[1]) and bool(parts[2]):
        return True
    return False


def _normalize_grant_atom(atom: str) -> str:
    """Return a lowercase-normalised form of a grant atom.

    Legacy aliases (e.g. ``group:operator`` → ``group:admin``) are *not*
    resolved here so that the user-visible stored value matches what was
    submitted.  Alias resolution only happens at grant-expansion time inside
    :func:`_expand_user_grants` and :func:`_expand_auto_grants`.
    """
    return str(atom or "").strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_module_name(raw_value: str) -> str:
    """Normalize a module id for use inside a permission atom."""
    return str(raw_value or "").strip().lower().replace("-", "_")


def _is_module_right_atom(atom: str) -> bool:
    """Return whether an atom has non-empty module and right path components.

    The right is not restricted to :data:`_MODULE_BUILTIN_RIGHTS`; modules may
    define additional scoped rights without requiring a framework deployment.
    """
    parts = _normalize_grant_atom(atom).split(":")
    return (
        len(parts) == 3
        and parts[0] == "module"
        and bool(parts[1])
        and bool(parts[2])
    )


def module_right_atom(module_name: str, right: str) -> str:
    """Build a module-scoped grant atom, or ``""`` for an empty component."""
    normalized_module = _normalize_module_name(module_name)
    normalized_right = _normalize_grant_atom(right)
    if not normalized_module or not normalized_right:
        return ""
    return f"module:{normalized_module}:{normalized_right}"


def _resolve_grant_atom(atom: str) -> str:
    """Return the canonical form of a grant atom, resolving all legacy aliases.

    This is intentionally used at expansion time, not write time.  Persisted
    values therefore round-trip unchanged through the configuration API while
    old names still map to current enforcement rights.
    """
    normalized = str(atom or "").strip().lower().replace(" ", "_").replace("-", "_")
    if normalized.startswith("group:"):
        group_name = normalized.split(":", 1)[1]
        group_name = _LEGACY_GROUP_ALIASES.get(group_name, group_name)
        return f"group:{group_name}"

    return _LEGACY_RIGHT_ALIASES.get(normalized, normalized)


def _configured_user_grant_groups(config: dict | None = None) -> dict[str, set[str]]:
    """Return built-in groups overlaid by runtime-defined right bundles.

    A custom definition with the same normalized name replaces the built-in
    bundle.  Values are defensively filtered to canonical application rights or
    syntactically valid module-scoped rights.  Nested group references are not
    expanded.
    """
    groups = {name: set(rights) for name, rights in _USER_GRANT_GROUPS.items()}
    custom = {}
    if isinstance(config, dict):
        custom = config.get("CHUCKBOT_GROUPS_JSON") or {}
    if not isinstance(custom, dict):
        return groups

    for raw_group, atoms in custom.items():
        group_name = _normalize_grant_atom(str(raw_group))
        if not group_name:
            continue
        normalized_atoms = set()
        for atom in atoms or []:
            normalized_atom = _resolve_grant_atom(str(atom))
            if normalized_atom in _USER_GRANT_RIGHTS or _is_module_right_atom(normalized_atom):
                normalized_atoms.add(normalized_atom)
        groups[group_name] = normalized_atoms
    return groups


def _normalize_groups_config_input(value, key: str) -> dict:
    """Validate a custom-group map at the runtime-configuration boundary.

    JSON strings and already-decoded mappings are accepted for compatibility.
    Group names and rights are normalized, duplicates are removed, and unknown
    rights are rejected rather than being stored for future interpretation.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{key} must be valid JSON") from exc

    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object mapping group name to rights")

    normalized = {}
    for raw_group, raw_atoms in value.items():
        group_name = _normalize_grant_atom(str(raw_group))
        if not group_name:
            continue
        if isinstance(raw_atoms, str):
            atoms = [part.strip() for part in raw_atoms.replace("\n", ",").split(",")]
        elif isinstance(raw_atoms, list):
            atoms = [str(item) for item in raw_atoms]
        else:
            raise ValueError(f"{key}.{group_name} must be a list or string")

        rights = set()
        for atom in atoms:
            normalized_atom = _resolve_grant_atom(atom)
            if not normalized_atom:
                continue
            if normalized_atom not in _USER_GRANT_RIGHTS and not _is_module_right_atom(normalized_atom):
                raise ValueError(f"Unknown right '{normalized_atom}' for group {group_name}")
            rights.add(normalized_atom)
        normalized[group_name] = sorted(rights)
    return normalized


def _normalize_group_descriptions_input(value, key: str) -> dict:
    """Validate group descriptions and cap each display-only value at 500 chars."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{key} must be valid JSON") from exc

    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object mapping group name to description")

    normalized = {}
    for raw_group, raw_description in value.items():
        group_name = _normalize_grant_atom(str(raw_group))
        if not group_name:
            continue
        description = str(raw_description or "").strip()
        if description:
            normalized[group_name] = description[:500]
    return normalized


def _normalize_user_grants_map_input(value, key: str) -> dict:
    """Validate a user-to-grant map and return stable, display-safe values.

    The API accepts list, comma-separated, and ``{groups, rights}`` forms.  User
    keys receive MediaWiki normalization, while grant atoms retain legacy aliases
    until evaluation.  Unknown rights fail validation.  Unknown *group* names are
    stored deliberately so a user assignment and its custom group definition can
    be submitted in either order; an unresolved group expands to no rights.
    """
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
        # Bare built-in/legacy group names are accepted as a convenience, but
        # persisted in the unambiguous ``group:<name>`` namespace.
        _all_valid_groups = (
            set(_configured_user_grant_groups().keys()) | set(_LEGACY_GROUP_ALIASES)
        )
        _all_valid_rights = set(_USER_GRANT_RIGHTS) | set(_LEGACY_RIGHT_ALIASES)
        for atom in atoms:
            normalized_atom = _normalize_grant_atom(atom)
            if not normalized_atom:
                continue

            if normalized_atom.startswith("group:"):
                # Group definitions may be added later, so accept unknown
                # group atoms here and resolve them when grants are expanded.
                group_name = normalized_atom.split(":", 1)[1]
                if not group_name:
                    raise ValueError(f"Unknown grant group '{group_name}' for {user}")
                user_atoms.add(normalized_atom)
                continue

            if normalized_atom in _all_valid_groups:
                user_atoms.add(f"group:{normalized_atom}")
                continue

            if normalized_atom not in _all_valid_rights and not _is_module_right_atom(normalized_atom):
                raise ValueError(f"Unknown right '{normalized_atom}' for {user}")

            user_atoms.add(normalized_atom)

        if user_atoms:
            normalized[user] = sorted(user_atoms)

    if len(normalized) > 1000:
        raise ValueError(f"{key} cannot contain more than 1000 users")

    return normalized


def _expand_user_grants(config: dict, username: str) -> set[str]:
    """Expand one user's direct grant atoms into enforceable rights.

    ``ROLLBACK_CONTROL_JSON`` takes precedence when present; the former
    ``USER_GRANTS_JSON`` name is a read-compatibility fallback.  Username lookup
    follows MediaWiki first-letter normalization.  Unknown groups, rights, and
    empty atoms contribute nothing, which keeps malformed policy fail-closed.
    """
    user = _normalize_username(username)
    if not user:
        return set()

    grants_map = (
        config.get("ROLLBACK_CONTROL_JSON")
        or config.get("USER_GRANTS_JSON")
        or {}
    )
    atoms = grants_map.get(user) or []
    expanded = set()
    groups = _configured_user_grant_groups(config)

    for raw_atom in atoms:
        # Resolve aliases only at the enforcement boundary: inspection and a
        # later write still expose the administrator's original spelling.
        atom = _resolve_grant_atom(raw_atom)
        if not atom:
            continue

        if atom.startswith("group:"):
            group_name = atom.split(":", 1)[1]
            expanded |= groups.get(group_name, set())
            continue

        if atom in groups:
            expanded |= groups[atom]
            continue

        if atom in _USER_GRANT_RIGHTS or _is_module_right_atom(atom):
            expanded.add(atom)

    return expanded


def _implicit_role_flags(
    config: dict, username: str, commons_groups: set[str] | None = None
) -> dict[str, bool]:
    """Return role-membership flags used by the grants-inspection response.

    ``authenticated`` is a syntactic flag for any non-empty normalized username;
    it neither verifies a session nor checks that the target account exists.
    Commons groups may be injected by the caller to avoid a duplicate API lookup.
    Other configured project/global selectors are resolved on demand and resolve
    to ``False`` when the corresponding Wikimedia request fails.
    """
    normalized_username = _normalize_username(username)
    if not normalized_username:
        return {role: False for role in _USER_IMPLICIT_FLAGS}

    groups = set(commons_groups if commons_groups is not None else get_user_groups(normalized_username))
    global_groups = set(get_user_global_groups(normalized_username))

    _router = _r()
    _is_bot_admin = _router.is_bot_admin if _router else is_bot_admin
    _is_maintainer = _router.is_maintainer if _router else is_maintainer
    flags = {
        "authenticated": True,
        "commons_admin": bool("sysop" in groups),
        "commons_rollbacker": bool("rollbacker" in groups),
        **{f"project:commons:{group}": True for group in groups},
        **{f"global:{group}": True for group in global_groups},
    }
    role_map = config.get("ROLE_GRANTS_JSON") or {}
    if isinstance(role_map, dict):
        for role in role_map:
            normalized_role = _normalize_auto_grant_role_name(role)
            if normalized_role not in flags and _is_valid_auto_grant_role(normalized_role):
                flags[normalized_role] = _auto_grant_role_enabled(
                    normalized_username,
                    normalized_role,
                )
    return flags


def _normalize_auto_grants_map_input(value, key: str) -> dict:
    """Validate Wikimedia-role grant policy from env, storage, or the API.

    Role selectors must be built-in, ``global:<group>``, or
    ``project:<wiki>:<group>``.  Grant payload compatibility mirrors direct user
    grants.  Unknown group references are safe to retain because they expand to
    nothing unless a corresponding custom group exists.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{key} must be valid JSON") from exc

    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object mapping role names to grants")

    normalized = {}

    for raw_role, raw_grants in value.items():
        role_name = str(raw_role or "").strip().lower().replace(" ", "_")
        if not role_name:
            continue

        role_name = _normalize_auto_grant_role_name(role_name)
        if not _is_valid_auto_grant_role(role_name):
            raise ValueError(f"Unknown auto-grant role '{role_name}'")

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
            raise ValueError(f"{key}.{role_name} must be a list/string/object")

        role_atoms = set()
        _all_valid_groups = (
            set(_configured_user_grant_groups().keys()) | set(_LEGACY_GROUP_ALIASES)
        )
        _all_valid_rights = set(_USER_GRANT_RIGHTS) | set(_LEGACY_RIGHT_ALIASES)
        for atom in atoms:
            normalized_atom = _normalize_grant_atom(atom)
            if not normalized_atom:
                continue

            if normalized_atom.startswith("group:"):
                # As with user grants, group atoms are stored even if a custom
                # group is defined in a later config update.
                group_name = normalized_atom.split(":", 1)[1]
                if not group_name:
                    raise ValueError(
                        f"Unknown grant group '{group_name}' for role {role_name}"
                    )
                role_atoms.add(normalized_atom)
                continue

            if normalized_atom in _all_valid_groups:
                role_atoms.add(f"group:{normalized_atom}")
                continue

            if normalized_atom not in _all_valid_rights and not _is_module_right_atom(normalized_atom):
                raise ValueError(
                    f"Unknown right '{normalized_atom}' for role {role_name}"
                )

            role_atoms.add(normalized_atom)

        normalized[role_name] = sorted(role_atoms)

    return normalized


def _expand_auto_grants(config: dict, username: str) -> set[str]:
    """Expand rights for every configured Wikimedia role held by ``username``.

    Roles are additive; they do not override or revoke direct grants.  Membership
    helpers return empty sets after remote errors, so unavailable identity data
    cannot accidentally enable a role.
    """
    role_map = config.get("ROLE_GRANTS_JSON") or {}
    if not isinstance(role_map, dict):
        return set()

    expanded = set()
    groups = _configured_user_grant_groups(config)

    for raw_role, role_atoms in role_map.items():
        role = _normalize_auto_grant_role_name(raw_role)
        if not _auto_grant_role_enabled(username, role):
            continue

        for raw_atom in role_atoms:
            # Resolve legacy aliases at expansion time.
            atom = _resolve_grant_atom(raw_atom)
            if not atom:
                continue

            if atom.startswith("group:"):
                group_name = atom.split(":", 1)[1]
                expanded |= groups.get(group_name, set())
                continue

            if atom in groups:
                expanded |= groups[atom]
                continue

            if atom in _USER_GRANT_RIGHTS or _is_module_right_atom(atom):
                expanded.add(atom)

    return expanded


def _expand_all_grants(config: dict, username: str) -> set[str]:
    """Return the additive union of direct-user and implicit-role rights.

    Deny-style precedence, such as the built-in ``read_only`` group, is applied
    later by :func:`router.permissions._user_permissions`; this layer only
    expands positive grant data.
    """
    return _expand_user_grants(config, username) | _expand_auto_grants(config, username)


def _get_user_grants_payload(
    target_username: str,
    config: dict,
    commons_groups: set[str] | None = None,
) -> dict:
    """Build the admin-facing explanation of one user's policy inputs.

    ``expanded_rights`` describes direct user atoms only; implicit role flags and
    local/project/global memberships are returned separately so the UI can show
    where automatic access originates without conflating it with stored grants.
    """
    normalized_username = _normalize_username(target_username)
    grants_map = (
        config.get("ROLLBACK_CONTROL_JSON")
        or config.get("USER_GRANTS_JSON")
        or {}
    )
    atoms = list(grants_map.get(normalized_username, []))

    groups = sorted(
        [atom.split(":", 1)[1] for atom in atoms if atom.startswith("group:")]
    )
    rights = sorted([atom for atom in atoms if not atom.startswith("group:")])
    expanded_rights = sorted(_expand_user_grants(config, normalized_username))

    resolved_groups = set(
        commons_groups
        if commons_groups is not None
        else get_user_groups(normalized_username)
    )
    implicit = _implicit_role_flags(
        config, normalized_username, commons_groups=resolved_groups
    )
    role_map = config.get("ROLE_GRANTS_JSON") or {}
    projects = {"commons"}
    if isinstance(role_map, dict):
        for role in role_map:
            parts = str(role or "").split(":")
            if len(parts) == 3 and parts[0] == "project" and parts[1]:
                projects.add(parts[1])
    project_groups = {
        # Commons membership was resolved above.  Only additional projects need
        # another network/cache lookup.
        project: sorted(
            resolved_groups
            if project == "commons"
            else set(get_project_user_groups(normalized_username, project))
        )
        for project in sorted(projects)
    }

    return {
        "username": target_username,
        "normalized_username": normalized_username,
        "atoms": sorted(atoms),
        "groups": groups,
        "rights": rights,
        "expanded_rights": expanded_rights,
        "implicit": implicit,
        "commons_groups": sorted(resolved_groups),
        "project_groups": project_groups,
        "global_groups": sorted(get_user_global_groups(normalized_username)),
    }


def _parse_user_grants_env(raw_value: str) -> dict:
    """Parse an env-sourced user grant map, ignoring the whole map if invalid.

    Environment policy is a startup baseline rather than request input, but it
    still crosses a configuration trust boundary and receives the same strict
    normalization as runtime updates.
    """
    if not raw_value:
        return {}

    try:
        return _normalize_user_grants_map_input(raw_value, "USER_GRANTS_JSON")
    except ValueError as exc:
        app.logger.warning("Invalid USER_GRANTS_JSON env var; ignoring: %s", exc)
        return {}


def _parse_role_grants_env(raw_value: str) -> dict:
    """Parse env-sourced role grants, logging and denying them if malformed."""
    if not raw_value:
        return {}

    try:
        return _normalize_auto_grants_map_input(raw_value, "ROLE_GRANTS_JSON")
    except ValueError as exc:
        app.logger.warning("Invalid ROLE_GRANTS_JSON env var; ignoring: %s", exc)
        return {}


def _merge_required_role_grants(role_grants: dict | None) -> dict:
    """Add non-privileged module admission required by installed policy.

    The returned mapping is a copy. Configured atoms remain additive, while the
    built-in mappings cannot be erased by a stale whole-map runtime override.
    """
    merged = {
        str(role): sorted({str(atom) for atom in atoms})
        for role, atoms in (role_grants or {}).items()
    }
    for role, required_atoms in _REQUIRED_ROLE_GRANTS.items():
        merged[role] = sorted({*merged.get(role, []), *required_atoms})
    return merged

def _parse_nonnegative_int(value, fallback: int) -> int:
    """Parse non-negative stored configuration or return a known-safe default."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback

    if parsed < 0:
        return fallback

    return parsed


def _runtime_authz_defaults() -> dict:
    """Build a fresh authorization baseline from env vars and built-in groups.

    Current JSON env vars take priority over their legacy equivalents when they
    contain a usable map.  Legacy username-list settings are then translated to
    equivalent group/right atoms and unioned into the user map.  For role grants,
    built-in Commons defaults are overlaid first by ``AUTO_GRANTS_JSON`` and then
    by the current ``ROLE_GRANTS_JSON`` setting.

    The returned mapping is newly built on every call so callers can overlay
    runtime values without mutating the process's import-time constants.
    """
    _router = _r()
    _extra = _router.EXTRA_AUTHORIZED_USERS if _router else EXTRA_AUTHORIZED_USERS
    _read_only = _router.USERS_READ_ONLY if _router else USERS_READ_ONLY
    _tester = _router.USERS_TESTER if _router else USERS_TESTER
    _from_diff = _router.USERS_GRANTED_FROM_DIFF if _router else USERS_GRANTED_FROM_DIFF
    _view_all = _router.USERS_GRANTED_VIEW_ALL if _router else USERS_GRANTED_VIEW_ALL
    _batch = _router.USERS_GRANTED_BATCH if _router else USERS_GRANTED_BATCH
    _cancel_any = (
        _router.USERS_GRANTED_CANCEL_ANY if _router else USERS_GRANTED_CANCEL_ANY
    )
    _retry_any = _router.USERS_GRANTED_RETRY_ANY if _router else USERS_GRANTED_RETRY_ANY
    _rate_limit = (
        _router.RATE_LIMIT_JOBS_PER_HOUR if _router else RATE_LIMIT_JOBS_PER_HOUR
    )
    _rate_tester = (
        _router.RATE_LIMIT_TESTER_JOBS_PER_HOUR
        if _router
        else RATE_LIMIT_TESTER_JOBS_PER_HOUR
    )
    # Prefer the current name, but continue reading old deployments that have
    # only USER_GRANTS_JSON configured.
    rollback_control = _parse_user_grants_env(os.getenv("ROLLBACK_CONTROL_JSON", ""))
    if not rollback_control:
        rollback_control = _parse_user_grants_env(os.getenv("USER_GRANTS_JSON", ""))

    def _add_user_atoms(users: set[str], atoms: list[str]) -> None:
        """Merge legacy username-list capabilities into normalized user atoms."""
        for user in users:
            normalized = _normalize_username(user)
            if not normalized:
                continue
            existing = set(rollback_control.get(normalized, []))
            existing.update(atoms)
            rollback_control[normalized] = sorted(existing)

    # Legacy env/list knobs are migration input only. The new model assigns
    # MediaWiki-style groups to users through ROLLBACK_CONTROL_JSON.
    _add_user_atoms(set(_extra), ["group:basic"])
    _add_user_atoms(set(_read_only), ["group:read_only"])
    _add_user_atoms(set(_tester), ["group:tester"])
    _add_user_atoms(set(_from_diff), ["group:rollbacker"])
    _add_user_atoms(set(_view_all), ["group:viewer"])
    _add_user_atoms(set(_batch), ["group:batch_runner"])
    _add_user_atoms(set(_cancel_any), ["cancel_any"])
    _add_user_atoms(set(_retry_any), ["retry_any"])

    role_grants = {
        # These roles authorize normal application access by default; they do
        # not inherit the larger app-maintainer permission set.
        "commons_admin": ["group:basic"],
        "commons_rollbacker": ["group:basic"],
    }
    legacy_auto_grants = _normalize_auto_grants_map_input(
        os.getenv("AUTO_GRANTS_JSON", "{}"), "AUTO_GRANTS_JSON"
    )
    role_grants.update(legacy_auto_grants)
    role_grants.update(_parse_role_grants_env(os.getenv("ROLE_GRANTS_JSON", "")))
    role_grants = _merge_required_role_grants(role_grants)

    return {
        "RATE_LIMIT_JOBS_PER_HOUR": int(_rate_limit),
        "RATE_LIMIT_TESTER_JOBS_PER_HOUR": int(_rate_tester),
        "ROLLBACK_CONTROL_JSON": rollback_control,
        "ROLE_GRANTS_JSON": role_grants,
        "CHUCKBOT_GROUPS_JSON": {
            name: sorted(rights) for name, rights in _USER_GRANT_GROUPS.items()
        },
        "CHUCKBOT_GROUP_DESCRIPTIONS_JSON": {},
    }


def _invalidate_runtime_authz_cache() -> None:
    """Force this process to read persisted authorization rows on next access."""
    global _runtime_authz_cache, _runtime_authz_cache_expiry
    _runtime_authz_cache = None
    _runtime_authz_cache_expiry = 0.0


def _load_runtime_authz_overrides() -> dict:
    """Load and cache normalized database overrides for the environment baseline.

    Persisted current-format keys take precedence over environment defaults.
    Legacy rows are translated only when the corresponding current JSON row is
    absent.  Database failures fall back to the environment baseline; malformed
    values fall back per key.  The resulting override map is cached in-process
    for :data:`_RUNTIME_AUTHZ_CACHE_TTL` seconds.
    """
    global _runtime_authz_cache, _runtime_authz_cache_expiry

    now = time.time()
    if _runtime_authz_cache is not None and now < _runtime_authz_cache_expiry:
        # Return the normalized map directly; _effective_runtime_authz_config
        # copies only the top-level mapping before exposing it to policy checks.
        return _runtime_authz_cache

    overrides = {}
    defaults = _runtime_authz_defaults()

    try:
        # Read legacy rows alongside current ones so upgrades do not require an
        # all-at-once database migration.
        rows = get_runtime_config(
            _RUNTIME_AUTHZ_ALLOWED_KEYS
            + sorted(_USER_SET_CONFIG_KEYS)
            + sorted(_LEGACY_JSON_CONFIG_KEYS)
        )
    except Exception:
        app.logger.warning("Failed to load runtime authz config; using env defaults.")
        rows = {}

    for key, raw_value in rows.items():
        if key in _USER_SET_CONFIG_KEYS:
            # Legacy list rows are migrated into ROLLBACK_CONTROL_JSON below.
            continue

        if key in _INT_CONFIG_KEYS:
            overrides[key] = _parse_nonnegative_int(raw_value, defaults[key])
            continue

        if key in _JSON_CONFIG_KEYS:
            # Persisted JSON is considered untrusted input because admins can
            # edit it at runtime; normalize it before it reaches permission checks.
            try:
                if key == "ROLE_GRANTS_JSON":
                    overrides[key] = _normalize_auto_grants_map_input(raw_value, key)
                elif key == "CHUCKBOT_GROUPS_JSON":
                    overrides[key] = _normalize_groups_config_input(raw_value, key)
                elif key == "CHUCKBOT_GROUP_DESCRIPTIONS_JSON":
                    overrides[key] = _normalize_group_descriptions_input(raw_value, key)
                else:
                    overrides[key] = _normalize_user_grants_map_input(raw_value, key)
            except ValueError:
                # A bad persisted value must never bypass normalization.  Using
                # the trusted baseline for this key is the fail-closed fallback.
                overrides[key] = defaults.get(key, {})

    legacy_user_updates = {}
    for key, raw_value in rows.items():
        if key in _USER_SET_CONFIG_KEYS:
            legacy_user_updates[key] = _parse_user_csv(raw_value)

    legacy_control = {}
    if rows.get("USER_GRANTS_JSON"):
        try:
            legacy_control.update(
                _normalize_user_grants_map_input(
                    rows["USER_GRANTS_JSON"], "USER_GRANTS_JSON"
                )
            )
        except ValueError:
            pass

    if legacy_user_updates or legacy_control:
        # Current ROLLBACK_CONTROL_JSON wins as a whole when present.  setdefault
        # below installs this migrated map only for older deployments.
        control = dict(defaults.get("ROLLBACK_CONTROL_JSON") or {})
        control.update(legacy_control)

        def _add(users: set[str], atoms: list[str]) -> None:
            """Merge one persisted legacy user set into the migration map."""
            for user in users:
                existing = set(control.get(user, []))
                existing.update(atoms)
                control[user] = sorted(existing)

        _add(legacy_user_updates.get("EXTRA_AUTHORIZED_USERS", set()), ["group:basic"])
        _add(legacy_user_updates.get("USERS_READ_ONLY", set()), ["group:read_only"])
        _add(legacy_user_updates.get("USERS_TESTER", set()), ["group:tester"])
        _add(legacy_user_updates.get("USERS_GRANTED_FROM_DIFF", set()), ["group:rollbacker"])
        _add(legacy_user_updates.get("USERS_GRANTED_VIEW_ALL", set()), ["group:viewer"])
        _add(legacy_user_updates.get("USERS_GRANTED_BATCH", set()), ["group:batch_runner"])
        _add(legacy_user_updates.get("USERS_GRANTED_CANCEL_ANY", set()), ["cancel_any"])
        _add(legacy_user_updates.get("USERS_GRANTED_RETRY_ANY", set()), ["retry_any"])
        overrides.setdefault("ROLLBACK_CONTROL_JSON", control)

    if rows.get("AUTO_GRANTS_JSON") and "ROLE_GRANTS_JSON" not in overrides:
        # ROLE_GRANTS_JSON is authoritative; AUTO_GRANTS_JSON is read only when
        # there is no current-format persisted role map.
        try:
            role_grants = dict(defaults.get("ROLE_GRANTS_JSON") or {})
            role_grants.update(
                _normalize_auto_grants_map_input(
                    rows["AUTO_GRANTS_JSON"], "AUTO_GRANTS_JSON"
                )
            )
            overrides["ROLE_GRANTS_JSON"] = role_grants
        except ValueError:
            pass

    _runtime_authz_cache = overrides
    _runtime_authz_cache_expiry = now + _RUNTIME_AUTHZ_CACHE_TTL
    return overrides


def _effective_runtime_authz_config() -> dict:
    """Return the current policy with persisted values winning over env defaults."""
    cfg = _runtime_authz_defaults()
    cfg.update(_load_runtime_authz_overrides())
    cfg["ROLE_GRANTS_JSON"] = _merge_required_role_grants(
        cfg.get("ROLE_GRANTS_JSON")
    )
    return cfg


def _serialize_runtime_authz_config(config: dict) -> dict:
    """Project internal policy values onto the writable runtime API schema."""
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
    """Normalize a bounded legacy username list retained for compatibility.

    New runtime writes no longer expose these list keys, but the helper remains
    available to older call paths.  It preserves MediaWiki-significant casing,
    removes duplicates, and rejects oversized payloads.
    """
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
    """Validate a partial runtime update and collect all field-level errors.

    Only the explicit current-format allowlist is writable.  No data is persisted
    here; routes can reject the entire request when ``errors`` is non-empty.
    """
    normalized = {}
    errors = []

    for key, value in payload.items():
        if key not in _RUNTIME_AUTHZ_ALLOWED_KEYS:
            errors.append(f"Unknown config key: {key}")
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
                if key == "ROLE_GRANTS_JSON":
                    normalized[key] = _normalize_auto_grants_map_input(value, key)
                elif key == "CHUCKBOT_GROUPS_JSON":
                    normalized[key] = _normalize_groups_config_input(value, key)
                elif key == "CHUCKBOT_GROUP_DESCRIPTIONS_JSON":
                    normalized[key] = _normalize_group_descriptions_input(value, key)
                else:
                    normalized[key] = _normalize_user_grants_map_input(value, key)
            except ValueError as exc:
                errors.append(str(exc))

    return normalized, errors


def _persist_runtime_authz_updates(updates: dict, updated_by: str) -> None:
    """Persist pre-normalized updates with attribution, then clear the local cache.

    Callers are responsible for authorization and must pass the output of
    :func:`_normalize_runtime_authz_updates`, not raw request JSON.
    """
    rows = {}
    for key, value in updates.items():
        if key in _JSON_CONFIG_KEYS:
            rows[key] = json.dumps(value, sort_keys=True)
        else:
            rows[key] = str(value)

    upsert_runtime_config(rows, updated_by=updated_by)
    _invalidate_runtime_authz_cache()


def get_user_groups(username, force_refresh: bool = False):
    """Return a user's Commons-local groups from a short-lived process cache.

    ``force_refresh`` bypasses, but still replaces, the cached value.  Network,
    HTTP, schema, and decoding failures are logged and cached as ``[]``.  Because
    callers use membership to add rights, that empty result is fail-closed.
    """
    now = time.time()

    cached = _group_cache.get(username)
    if not force_refresh and cached and (now - cached["ts"] < GROUP_CACHE_TTL):
        return cached["groups"]

    url = WIKI_API_URL
    params = {
        "action": "query",
        "list": "users",
        "ususers": username,
        "usprop": "groups",
        "format": "json",
    }

    try:
        resp = requests.get(url, params=params, headers=http_headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        users = data.get("query", {}).get("users", [])
        groups = users[0].get("groups", []) if users else []
    except Exception:
        app.logger.exception("Failed to fetch groups for %s", username)
        groups = []

    # Negative results use the same TTL as successful ones: this trades delayed
    # recovery for bounded upstream traffic, and a negative entry grants nothing.
    _group_cache[username] = {"groups": groups, "ts": now}
    return groups


def _project_api_url(project: str) -> str:
    """Resolve an admin-configured Wikimedia project id or host to its API URL.

    Common project database names receive explicit mappings; other ``*wiki``
    values are treated as Wikipedia language projects.  Dotted values are treated
    as Wikimedia-style hosts.  This helper only constructs the endpoint—role
    selector validation occurs before authorization policy is persisted.
    """
    value = str(project or "").strip().lower()
    if value in {"commons", "commonswiki"}:
        return "https://commons.wikimedia.org/w/api.php"
    if value in {"wikidata", "wikidatawiki"}:
        return "https://www.wikidata.org/w/api.php"
    if value in {"meta", "metawiki"}:
        return "https://meta.wikimedia.org/w/api.php"
    if "." in value:
        host = value
        if not host.endswith(".org"):
            host = f"{host}.org"
        return f"https://{host}/w/api.php"
    if value.endswith("wiki") and len(value) > 4:
        return f"https://{value[:-4]}.wikipedia.org/w/api.php"
    return f"https://{value}.wikipedia.org/w/api.php"


def get_project_userright_groups(project: str, force_refresh: bool = False) -> list[str]:
    """Return group names advertised by a project's siteinfo endpoint.

    This list populates policy-editing choices; it does not itself grant access.
    Results, including failure-induced empty lists, share the group-cache TTL.
    """
    normalized_project = str(project or "").strip().lower()
    if not normalized_project:
        return []

    # Prefixes keep site metadata from colliding with per-user membership data
    # in the shared process-local cache.
    cache_key = f"siteinfo-groups:{normalized_project}"
    now = time.time()
    cached = _group_cache.get(cache_key)
    if not force_refresh and cached and (now - cached["ts"] < GROUP_CACHE_TTL):
        return cached["groups"]

    params = {
        "action": "query",
        "meta": "siteinfo",
        "siprop": "usergroups",
        "format": "json",
    }

    try:
        resp = requests.get(
            _project_api_url(normalized_project),
            params=params,
            headers=http_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_groups = data.get("query", {}).get("usergroups", [])
        groups = sorted(
            {
                str(group.get("name") or "").strip()
                for group in raw_groups
                if str(group.get("name") or "").strip()
            }
        )
    except Exception:
        app.logger.exception("Failed to fetch %s userright groups", normalized_project)
        groups = []

    _group_cache[cache_key] = {"groups": groups, "ts": now}
    return groups


def get_project_user_groups(
    username: str,
    project: str,
    force_refresh: bool = False,
):
    """Return one user's local groups on an admin-configured Wikimedia project.

    Membership is cached by project and supplied username.  Any remote failure
    yields and caches an empty list so project-backed auto grants fail closed.
    """
    normalized_project = str(project or "").strip().lower()
    cache_key = f"project:{normalized_project}:{username}"
    now = time.time()

    cached = _group_cache.get(cache_key)
    if not force_refresh and cached and (now - cached["ts"] < GROUP_CACHE_TTL):
        return cached["groups"]

    params = {
        "action": "query",
        "list": "users",
        "ususers": username,
        "usprop": "groups",
        "format": "json",
    }

    try:
        resp = requests.get(
            _project_api_url(normalized_project),
            params=params,
            headers=http_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        users = data.get("query", {}).get("users", [])
        groups = users[0].get("groups", []) if users else []
    except Exception:
        app.logger.exception(
            "Failed to fetch %s groups for %s", normalized_project, username
        )
        groups = []

    _group_cache[cache_key] = {"groups": groups, "ts": now}
    return groups


def get_user_global_groups(username, force_refresh: bool = False):
    """Return a MediaWiki-normalized user's CentralAuth global groups.

    CentralAuth has returned both list- and mapping-shaped group data over time;
    both forms are accepted.  Failures return an empty cached list, denying all
    global-role grants until a later refresh.
    """
    normalized_username = _normalize_username(username)
    cache_key = f"global:{normalized_username}"
    now = time.time()

    cached = _group_cache.get(cache_key)
    if not force_refresh and cached and (now - cached["ts"] < GROUP_CACHE_TTL):
        return cached["groups"]

    params = {
        "action": "query",
        "meta": "globaluserinfo",
        "guiuser": normalized_username,
        "guiprop": "groups",
        "format": "json",
    }

    try:
        resp = requests.get(
            WIKI_API_URL,
            params=params,
            headers=http_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        global_info = data.get("query", {}).get("globaluserinfo", {})
        raw_groups = global_info.get("groups", [])
        if isinstance(raw_groups, dict):
            raw_groups = raw_groups.keys()
        groups = sorted({str(group).strip() for group in raw_groups if str(group).strip()})
    except Exception:
        app.logger.exception("Failed to fetch global groups for %s", normalized_username)
        groups = []

    _group_cache[cache_key] = {"groups": groups, "ts": now}
    return groups


def get_global_userright_groups(force_refresh: bool = False) -> list[str]:
    """Return CentralAuth group names offered by the policy editor.

    This is discovery metadata rather than membership data.  Empty failure
    results are cached briefly to avoid repeatedly hitting a degraded API.
    """
    cache_key = "siteinfo-global-groups"
    now = time.time()
    cached = _group_cache.get(cache_key)
    if not force_refresh and cached and (now - cached["ts"] < GROUP_CACHE_TTL):
        return cached["groups"]

    params = {
        "action": "query",
        "list": "globalgroups",
        "format": "json",
    }

    try:
        resp = requests.get(
            WIKI_API_URL,
            params=params,
            headers=http_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_groups = data.get("query", {}).get("globalgroups", [])
        groups = sorted(
            {
                str(group.get("name") or group.get("group") or "").strip()
                for group in raw_groups
                if str(group.get("name") or group.get("group") or "").strip()
            }
        )
    except Exception:
        app.logger.exception("Failed to fetch global userright groups")
        groups = []

    _group_cache[cache_key] = {"groups": groups, "ts": now}
    return groups


def _auto_grant_role_enabled(username: str, role_name: str) -> bool:
    """Evaluate a normalized role selector against the supplied username.

    The special ``authenticated`` selector trusts the caller's non-empty username
    and performs no credential check; enforcement callers must obtain it from the
    authenticated session.  Wikimedia local/global membership checks fail closed
    because their lookup helpers return empty lists on errors.  Unknown selectors
    return ``False``.
    """
    normalized_username = _normalize_username(username)
    role_name = _normalize_auto_grant_role_name(role_name)
    if not normalized_username:
        return False
    if role_name == "authenticated":
        # This means "authenticated upstream", not "the account exists".
        return True
    if role_name == "commons_admin":
        return "sysop" in set(get_user_groups(normalized_username))
    if role_name == "commons_rollbacker":
        return "rollbacker" in set(get_user_groups(normalized_username))

    parts = role_name.split(":")
    if len(parts) == 2 and parts[0] == "global":
        return parts[1] in set(get_user_global_groups(normalized_username))
    if len(parts) == 3 and parts[0] == "project":
        return parts[2] in set(get_project_user_groups(normalized_username, parts[1]))
    return False


def user_has_module_right(username: str, module_name: str, right: str) -> bool:
    """Check a module right, treating ``manage_modules`` as a global override.

    The override is intentionally broad in current policy: it satisfies every
    module-scoped right, including module-defined sensitive actions such as live
    apply and future rights not yet known to the framework. Empty
    identities/components and other ungranted rights fail closed. This helper
    evaluates configured grants only; callers apply maintainer hierarchy
    separately in the permissions layer.
    """
    if not username:
        return False
    config = _effective_runtime_authz_config()
    grants = _expand_all_grants(config, username)
    atom = module_right_atom(module_name, right)
    if not atom:
        return False
    return atom in grants or "manage_modules" in grants


def is_bot_admin(username: str) -> bool:
    """Return whether a username is in the process-configured bot-admin set.

    Matching ignores surrounding whitespace and case.  Permission assembly gives
    the bot-admin-only cancellation power inside its maintainer branch; other
    bot-admin exceptions are documented at their individual policy checks.
    """
    if not username:
        return False
    _router = _r()
    accounts = _router.BOT_ADMIN_ACCOUNTS if _router else BOT_ADMIN_ACCOUNTS
    return username.strip().lower() in accounts
