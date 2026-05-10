"""Authorization configuration: env-var parsing, user grants, runtime config management."""

import json
import os
import time

import sys as _sys

import requests

from app import BOT_ADMIN_ACCOUNTS, flask_app as app, is_maintainer  # noqa: F401
from router.framework_config import (
    ALLOWED_GROUPS as FRAMEWORK_ALLOWED_GROUPS,
    WIKI_API_URL,
)
from toolsdb import get_runtime_config, upsert_runtime_config


def _r():
    """Return the router package module (supports test-side patching via router.X)."""
    return _sys.modules.get("router")


GROUP_CACHE_TTL = 300
_group_cache: dict = {}
ALLOWED_GROUPS = FRAMEWORK_ALLOWED_GROUPS


def _env_user_set(env_var: str) -> set[str]:
    """Parse a comma-separated environment variable into a lower-cased set of usernames."""
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

_MODULE_BUILTIN_RIGHTS = {
    "access",
    "estop",
    "manage",
    "view_jobs",
    "run_jobs",
    "edit_config",
}

_USER_GRANT_GROUPS = {
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

_USER_IMPLICIT_FLAGS = (
    "authenticated",
    "commons_admin",
    "commons_rollbacker",
)

_AUTO_GRANT_ROLE_KEYS = set(_USER_IMPLICIT_FLAGS)

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
}

_LEGACY_JSON_CONFIG_KEYS = {
    "USER_GRANTS_JSON",
    "AUTO_GRANTS_JSON",
}

_RUNTIME_AUTHZ_ALLOWED_KEYS = sorted(_INT_CONFIG_KEYS | _JSON_CONFIG_KEYS)
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
    if not cleaned:
        return ""
    return cleaned[0].upper() + cleaned[1:]


def _normalize_auto_grant_role_name(raw_value: str) -> str:
    value = str(raw_value or "").strip().lower().replace(" ", "_")
    if value in {"commons_admin", "project:commons:sysop"}:
        return "commons_admin"
    if value in {"commons_rollbacker", "project:commons:rollbacker"}:
        return "commons_rollbacker"
    return value


def _is_valid_auto_grant_role(role_name: str) -> bool:
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
    return str(raw_value or "").strip().lower().replace("-", "_")


def _is_module_right_atom(atom: str) -> bool:
    parts = _normalize_grant_atom(atom).split(":")
    return (
        len(parts) == 3
        and parts[0] == "module"
        and bool(parts[1])
        and bool(parts[2])
    )


def module_right_atom(module_name: str, right: str) -> str:
    normalized_module = _normalize_module_name(module_name)
    normalized_right = _normalize_grant_atom(right)
    if not normalized_module or not normalized_right:
        return ""
    return f"module:{normalized_module}:{normalized_right}"


def _resolve_grant_atom(atom: str) -> str:
    """Return the canonical form of a grant atom, resolving all legacy aliases.

    Used at expansion time (``_expand_user_grants``, ``_expand_auto_grants``).
    """
    normalized = str(atom or "").strip().lower().replace(" ", "_").replace("-", "_")
    if normalized.startswith("group:"):
        group_name = normalized.split(":", 1)[1]
        group_name = _LEGACY_GROUP_ALIASES.get(group_name, group_name)
        return f"group:{group_name}"

    return _LEGACY_RIGHT_ALIASES.get(normalized, normalized)


def _configured_user_grant_groups(config: dict | None = None) -> dict[str, set[str]]:
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
        _all_valid_groups = (
            set(_configured_user_grant_groups().keys()) | set(_LEGACY_GROUP_ALIASES)
        )
        _all_valid_rights = set(_USER_GRANT_RIGHTS) | set(_LEGACY_RIGHT_ALIASES)
        for atom in atoms:
            normalized_atom = _normalize_grant_atom(atom)
            if not normalized_atom:
                continue

            if normalized_atom.startswith("group:"):
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
        # Resolve legacy aliases at expansion time (atoms are stored as-is).
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
    return _expand_user_grants(config, username) | _expand_auto_grants(config, username)


def _get_user_grants_payload(
    target_username: str,
    config: dict,
    commons_groups: set[str] | None = None,
) -> dict:
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
    if not raw_value:
        return {}

    try:
        return _normalize_user_grants_map_input(raw_value, "USER_GRANTS_JSON")
    except ValueError as exc:
        app.logger.warning("Invalid USER_GRANTS_JSON env var; ignoring: %s", exc)
        return {}


def _parse_role_grants_env(raw_value: str) -> dict:
    if not raw_value:
        return {}

    try:
        return _normalize_auto_grants_map_input(raw_value, "ROLE_GRANTS_JSON")
    except ValueError as exc:
        app.logger.warning("Invalid ROLE_GRANTS_JSON env var; ignoring: %s", exc)
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
    rollback_control = _parse_user_grants_env(os.getenv("ROLLBACK_CONTROL_JSON", ""))
    if not rollback_control:
        rollback_control = _parse_user_grants_env(os.getenv("USER_GRANTS_JSON", ""))

    def _add_user_atoms(users: set[str], atoms: list[str]) -> None:
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
        "commons_admin": ["group:basic"],
        "commons_rollbacker": ["group:basic"],
    }
    legacy_auto_grants = _normalize_auto_grants_map_input(
        os.getenv("AUTO_GRANTS_JSON", "{}"), "AUTO_GRANTS_JSON"
    )
    role_grants.update(legacy_auto_grants)
    role_grants.update(_parse_role_grants_env(os.getenv("ROLE_GRANTS_JSON", "")))

    return {
        "RATE_LIMIT_JOBS_PER_HOUR": int(_rate_limit),
        "RATE_LIMIT_TESTER_JOBS_PER_HOUR": int(_rate_tester),
        "ROLLBACK_CONTROL_JSON": rollback_control,
        "ROLE_GRANTS_JSON": role_grants,
        "CHUCKBOT_GROUPS_JSON": {
            name: sorted(rights) for name, rights in _USER_GRANT_GROUPS.items()
        },
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
            try:
                if key == "ROLE_GRANTS_JSON":
                    overrides[key] = _normalize_auto_grants_map_input(raw_value, key)
                elif key == "CHUCKBOT_GROUPS_JSON":
                    overrides[key] = _normalize_groups_config_input(raw_value, key)
                else:
                    overrides[key] = _normalize_user_grants_map_input(raw_value, key)
            except ValueError:
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
        control = dict(defaults.get("ROLLBACK_CONTROL_JSON") or {})
        control.update(legacy_control)

        def _add(users: set[str], atoms: list[str]) -> None:
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
                else:
                    normalized[key] = _normalize_user_grants_map_input(value, key)
            except ValueError as exc:
                errors.append(str(exc))

    return normalized, errors


def _persist_runtime_authz_updates(updates: dict, updated_by: str) -> None:
    rows = {}
    for key, value in updates.items():
        if key in _JSON_CONFIG_KEYS:
            rows[key] = json.dumps(value, sort_keys=True)
        else:
            rows[key] = str(value)

    upsert_runtime_config(rows, updated_by=updated_by)
    _invalidate_runtime_authz_cache()


def get_user_groups(username, force_refresh: bool = False):
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


def _project_api_url(project: str) -> str:
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
    """Return user group names advertised by a wiki's siteinfo API."""
    normalized_project = str(project or "").strip().lower()
    if not normalized_project:
        return []

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
        resp = requests.get(_project_api_url(normalized_project), params=params, timeout=10)
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
        resp = requests.get(WIKI_API_URL, params=params, timeout=10)
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
    """Return CentralAuth global group names from the Wikimedia API."""
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
        resp = requests.get(WIKI_API_URL, params=params, timeout=10)
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
    normalized_username = _normalize_username(username)
    role_name = _normalize_auto_grant_role_name(role_name)
    if not normalized_username:
        return False
    if role_name == "authenticated":
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
    if not username:
        return False
    config = _effective_runtime_authz_config()
    grants = _expand_all_grants(config, username)
    atom = module_right_atom(module_name, right)
    if not atom:
        return False
    return atom in grants or "manage_modules" in grants


def is_bot_admin(username: str) -> bool:
    """Return True if the user is one of the hardcoded bot-admin accounts (e.g. chuckbot).

    Bot admins sit at the top of the user hierarchy: chuckbot > maintainer > admin > regular.
    """
    if not username:
        return False
    _router = _r()
    accounts = _router.BOT_ADMIN_ACCOUNTS if _router else BOT_ADMIN_ACCOUNTS
    return username.strip().lower() in accounts
