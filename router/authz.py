"""Authorization configuration: env-var parsing, user grants, runtime config management."""

import json
import os
import time

import sys as _sys

import requests

from app import BOT_ADMIN_ACCOUNTS, flask_app as app, is_maintainer  # noqa: F401
from router.framework_config import WIKI_API_URL
from toolsdb import get_runtime_config, upsert_runtime_config


def _r():
    """Return the router package module (supports test-side patching via router.X)."""
    return _sys.modules.get("router")


GROUP_CACHE_TTL = 300
_group_cache: dict = {}


def _env_user_set(env_var: str) -> set[str]:
    """Parse a comma-separated environment variable into a lower-cased set of usernames."""
    return {u.strip().lower() for u in os.getenv(env_var, "").split(",") if u.strip()}


ALLOWED_GROUPS = _env_user_set("ALLOWED_GROUPS") or {"sysop", "rollbacker"}


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
    "rollback_diff",
    "rollback_account",
    "rollback_batch",
    "rollback_diff_dry_run_only",
    "approve_jobs",
    "autoapprove_jobs",
    "force_dry_run",
    "view_all",
    "edit_config",
    "manage_user_grants",
    "cancel_any",
    "retry_any",
}

_USER_GRANT_GROUPS = {
    "viewer": {"view_all"},
    "rollbacker": {"rollback_diff", "rollback_account"},
    "rollbacker_dry_run": {
        "rollback_diff",
        "rollback_account",
        "rollback_diff_dry_run_only",
    },
    "batch_runner": {"rollback_batch"},
    "jobs_moderator": {
        "approve_jobs",
        "force_dry_run",
        "cancel_any",
        "retry_any",
    },
    "admin": {
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
    "bot_admin",
    "maintainer",
    "commons_admin",
    "commons_rollbacker",
    "tester",
    "read_only",
    "extra_authorized",
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
    "USER_GRANTS_JSON",
    "AUTO_GRANTS_JSON",
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
    """Return a lowercase-normalised form of a grant atom.

    Legacy aliases (e.g. ``group:operator`` → ``group:admin``) are *not*
    resolved here so that the user-visible stored value matches what was
    submitted.  Alias resolution only happens at grant-expansion time inside
    :func:`_expand_user_grants` and :func:`_expand_auto_grants`.
    """
    return str(atom or "").strip().lower().replace(" ", "_").replace("-", "_")


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
        _all_valid_groups = set(_USER_GRANT_GROUPS) | set(_LEGACY_GROUP_ALIASES)
        _all_valid_rights = set(_USER_GRANT_RIGHTS) | set(_LEGACY_RIGHT_ALIASES)
        for atom in atoms:
            normalized_atom = _normalize_grant_atom(atom)
            if not normalized_atom:
                continue

            if normalized_atom.startswith("group:"):
                group_name = normalized_atom.split(":", 1)[1]
                if group_name not in _all_valid_groups:
                    raise ValueError(f"Unknown grant group '{group_name}' for {user}")
                user_atoms.add(normalized_atom)
                continue

            if normalized_atom in _all_valid_groups:
                user_atoms.add(f"group:{normalized_atom}")
                continue

            if normalized_atom not in _all_valid_rights:
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
        # Resolve legacy aliases at expansion time (atoms are stored as-is).
        atom = _resolve_grant_atom(raw_atom)
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


def _implicit_role_flags(
    config: dict, username: str, commons_groups: set[str] | None = None
) -> dict[str, bool]:
    normalized_username = _normalize_username(username)
    if not normalized_username:
        return {role: False for role in _USER_IMPLICIT_FLAGS}

    groups = set(
        commons_groups
        if commons_groups is not None
        else get_user_groups(normalized_username)
    )

    _router = _r()
    _is_bot_admin = _router.is_bot_admin if _router else is_bot_admin
    _is_maintainer = _router.is_maintainer if _router else is_maintainer
    return {
        "authenticated": True,
        "bot_admin": bool(_is_bot_admin(normalized_username)),
        "maintainer": bool(_is_maintainer(normalized_username)),
        "commons_admin": bool("sysop" in groups),
        "commons_rollbacker": bool("rollbacker" in groups),
        "tester": bool(normalized_username in config["USERS_TESTER"]),
        "read_only": bool(normalized_username in config["USERS_READ_ONLY"]),
        "extra_authorized": bool(
            normalized_username in config["EXTRA_AUTHORIZED_USERS"]
        ),
    }


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

        if role_name not in _AUTO_GRANT_ROLE_KEYS:
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
        _all_valid_groups = set(_USER_GRANT_GROUPS) | set(_LEGACY_GROUP_ALIASES)
        _all_valid_rights = set(_USER_GRANT_RIGHTS) | set(_LEGACY_RIGHT_ALIASES)
        for atom in atoms:
            normalized_atom = _normalize_grant_atom(atom)
            if not normalized_atom:
                continue

            if normalized_atom.startswith("group:"):
                group_name = normalized_atom.split(":", 1)[1]
                if group_name not in _all_valid_groups:
                    raise ValueError(
                        f"Unknown grant group '{group_name}' for role {role_name}"
                    )
                role_atoms.add(normalized_atom)
                continue

            if normalized_atom in _all_valid_groups:
                role_atoms.add(f"group:{normalized_atom}")
                continue

            if normalized_atom not in _all_valid_rights:
                raise ValueError(
                    f"Unknown right '{normalized_atom}' for role {role_name}"
                )

            role_atoms.add(normalized_atom)

        normalized[role_name] = sorted(role_atoms)

    return normalized


def _expand_auto_grants(config: dict, username: str) -> set[str]:
    role_map = config.get("AUTO_GRANTS_JSON") or {}
    if not isinstance(role_map, dict):
        return set()

    implicit_flags = _implicit_role_flags(config, username)
    expanded = set()

    for role, enabled in implicit_flags.items():
        if not enabled:
            continue

        role_atoms = role_map.get(role) or []
        for raw_atom in role_atoms:
            # Resolve legacy aliases at expansion time.
            atom = _resolve_grant_atom(raw_atom)
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


def _expand_all_grants(config: dict, username: str) -> set[str]:
    return _expand_user_grants(config, username) | _expand_auto_grants(config, username)


def _get_user_grants_payload(
    target_username: str,
    config: dict,
    commons_groups: set[str] | None = None,
) -> dict:
    normalized_username = _normalize_username(target_username)
    grants_map = config.get("USER_GRANTS_JSON") or {}
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

    return {
        "username": target_username,
        "normalized_username": normalized_username,
        "atoms": sorted(atoms),
        "groups": groups,
        "rights": rights,
        "expanded_rights": expanded_rights,
        "implicit": implicit,
        "commons_groups": sorted(resolved_groups),
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
    return {
        "EXTRA_AUTHORIZED_USERS": set(_extra),
        "USERS_READ_ONLY": set(_read_only),
        "USERS_TESTER": set(_tester),
        "USERS_GRANTED_FROM_DIFF": set(_from_diff),
        "USERS_GRANTED_VIEW_ALL": set(_view_all),
        "USERS_GRANTED_BATCH": set(_batch),
        "USERS_GRANTED_CANCEL_ANY": set(_cancel_any),
        "USERS_GRANTED_RETRY_ANY": set(_retry_any),
        "RATE_LIMIT_JOBS_PER_HOUR": int(_rate_limit),
        "RATE_LIMIT_TESTER_JOBS_PER_HOUR": int(_rate_tester),
        "USER_GRANTS_JSON": _parse_user_grants_env(os.getenv("USER_GRANTS_JSON", "")),
        "AUTO_GRANTS_JSON": _normalize_auto_grants_map_input(
            os.getenv("AUTO_GRANTS_JSON", "{}"), "AUTO_GRANTS_JSON"
        ),
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
                if key == "AUTO_GRANTS_JSON":
                    overrides[key] = _normalize_auto_grants_map_input(raw_value, key)
                else:
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
                if key == "AUTO_GRANTS_JSON":
                    normalized[key] = _normalize_auto_grants_map_input(value, key)
                else:
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


def is_bot_admin(username: str) -> bool:
    """Return True if the user is one of the hardcoded bot-admin accounts (e.g. chuckbot).

    Bot admins sit at the top of the user hierarchy: chuckbot > maintainer > admin > regular.
    """
    if not username:
        return False
    _router = _r()
    accounts = _router.BOT_ADMIN_ACCOUNTS if _router else BOT_ADMIN_ACCOUNTS
    return username.strip().lower() in accounts
