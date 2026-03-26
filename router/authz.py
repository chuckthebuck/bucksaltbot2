"""Authorization configuration: env-var parsing, user grants, runtime config management."""

import json
import os
import time

from app import BOT_ADMIN_ACCOUNTS, flask_app as app, is_maintainer  # noqa: F401
from toolsdb import get_runtime_config, upsert_runtime_config

ALLOWED_GROUPS = {"sysop", "rollbacker"}
GROUP_CACHE_TTL = 300
_group_cache: dict = {}


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

_CONFIG_EDIT_PRIMARY_ACCOUNT = os.getenv("CONFIG_EDIT_PRIMARY_ACCOUNT", "chuckbot").strip().lower()

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

_RUNTIME_AUTHZ_ALLOWED_KEYS = sorted(_USER_SET_CONFIG_KEYS | _INT_CONFIG_KEYS | _JSON_CONFIG_KEYS)
_RUNTIME_AUTHZ_CACHE_TTL = 60
_runtime_authz_cache = None
_runtime_authz_cache_expiry = 0.0


_REQUEST_TYPE_QUEUE = "queue"
_REQUEST_TYPE_BATCH = "batch"
_REQUEST_TYPE_DIFF = "diff"

_REQUEST_STATUS_PENDING_APPROVAL = "pending_approval"

_APPROVAL_REQUIRED_ADMIN = "admin"
_APPROVAL_REQUIRED_MAINTAINER = "maintainer"

_ENDPOINT_BATCH = "batch"
_ENDPOINT_FROM_DIFF = "from_diff"
_ENDPOINT_FROM_ACCOUNT = "from_account"

_ALLOWED_DIFF_REQUEST_ENDPOINTS = frozenset({_ENDPOINT_FROM_DIFF, _ENDPOINT_FROM_ACCOUNT})
_ALLOWED_REQUEST_TYPES = frozenset({_REQUEST_TYPE_QUEUE, _REQUEST_TYPE_BATCH, _REQUEST_TYPE_DIFF})


def is_bot_admin(username: str) -> bool:
    """Return True if the user is one of the hardcoded bot-admin accounts (e.g. chuckbot).

    Bot admins sit at the top of the user hierarchy: chuckbot > maintainer > admin > regular.
    """
    if not username:
        return False
    return username.strip().lower() in BOT_ADMIN_ACCOUNTS


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
        "extra_authorized": bool(normalized_username in config["EXTRA_AUTHORIZED_USERS"]),
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
