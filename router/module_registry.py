"""Module manifest parsing and registry helpers.

This is the first step toward a module-first framework: a module must be
declared by a manifest, must expose either a UI or cron surface, and may opt
into its own OAuth consumer instead of the framework default worker consumer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from pathlib import Path
from typing import Any

from toolsdb import get_conn

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None  # type: ignore[assignment]


MODULE_MANIFEST_FILENAMES = ("module.toml", "module.json")


@dataclass(frozen=True)
class ModuleCronJob:
    """Declarative cron job entry from a module manifest."""

    name: str
    schedule: str
    endpoint: str
    timeout_seconds: int = 300
    enabled: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModuleDefinition:
    """Validated module manifest used by the framework registry."""

    name: str
    repo_url: str
    entry_point: str
    ui_enabled: bool = False
    cron_jobs: tuple[ModuleCronJob, ...] = ()
    buildpacks: tuple[str, ...] = ()
    oauth_consumer_mode: str = "default"
    oauth_consumer_key_env: str | None = None
    oauth_consumer_secret_env: str | None = None
    redis_namespace: str | None = None
    title: str | None = None

    @property
    def is_cron_only(self) -> bool:
        return not self.ui_enabled and bool(self.cron_jobs)

    @property
    def is_ui_enabled(self) -> bool:
        return bool(self.ui_enabled)

    @property
    def exposes_module_surface(self) -> bool:
        return self.ui_enabled or bool(self.cron_jobs)

    @property
    def has_custom_buildpacks(self) -> bool:
        return bool(self.buildpacks)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cron_jobs"] = [job.as_dict() for job in self.cron_jobs]
        return payload


@dataclass(frozen=True)
class ModuleRecord:
    """Module definition as stored in the registry database."""

    definition: ModuleDefinition
    enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = self.definition.as_dict()
        payload["enabled"] = bool(self.enabled)
        return payload


def _default_redis_namespace(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    return normalized.strip("_") or "module"


def _load_manifest_text(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)

    raw_text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(raw_text)

    if path.suffix.lower() in {".toml", ".tml"}:
        if tomllib is None:
            raise RuntimeError("TOML manifests require Python 3.11+")
        return tomllib.loads(raw_text)

    raise ValueError(f"Unsupported module manifest format: {path.suffix}")


def _coerce_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off", ""}:
            return False
    raise ValueError(f"{field_name} must be a boolean value")


def _coerce_positive_int(value: Any, *, field_name: str, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def _parse_cron_jobs(raw_jobs: Any) -> tuple[ModuleCronJob, ...]:
    if raw_jobs in (None, ""):
        return ()
    if not isinstance(raw_jobs, list):
        raise ValueError("cron jobs must be a list")

    jobs: list[ModuleCronJob] = []
    for index, raw_job in enumerate(raw_jobs, start=1):
        if not isinstance(raw_job, dict):
            raise ValueError(f"cron job {index} must be an object")

        name = str(raw_job.get("name") or raw_job.get("job_id") or "").strip()
        schedule = str(raw_job.get("schedule") or "").strip()
        endpoint = str(raw_job.get("endpoint") or "").strip()
        timeout_seconds = _coerce_positive_int(
            raw_job.get("timeout_seconds"),
            field_name=f"cron job {index} timeout_seconds",
            default=300,
        )
        enabled = _coerce_bool(
            raw_job.get("enabled", True),
            field_name=f"cron job {index} enabled",
        )

        if not name:
            raise ValueError(f"cron job {index} requires a name")
        if not schedule:
            raise ValueError(f"cron job {index} requires a schedule")
        if not endpoint:
            raise ValueError(f"cron job {index} requires an endpoint")

        jobs.append(
            ModuleCronJob(
                name=name,
                schedule=schedule,
                endpoint=endpoint,
                timeout_seconds=timeout_seconds,
                enabled=enabled,
            )
        )

    return tuple(jobs)


def _parse_buildpacks(raw_buildpacks: Any) -> tuple[str, ...]:
    if raw_buildpacks in (None, ""):
        return ()
    if isinstance(raw_buildpacks, str):
        raw_buildpacks = [raw_buildpacks]
    if not isinstance(raw_buildpacks, list):
        raise ValueError("buildpacks must be a list of strings")

    buildpacks = []
    for index, raw_buildpack in enumerate(raw_buildpacks, start=1):
        buildpack = str(raw_buildpack or "").strip()
        if not buildpack:
            raise ValueError(f"buildpack {index} must be a non-empty string")
        buildpacks.append(buildpack)

    return tuple(buildpacks)


def parse_module_definition(raw: dict[str, Any]) -> ModuleDefinition:
    """Validate and normalize a module manifest dictionary."""
    if not isinstance(raw, dict):
        raise ValueError("module manifest must be an object")

    name = str(raw.get("name") or "").strip()
    repo_url = str(raw.get("repo") or raw.get("repo_url") or "").strip()
    entry_point = str(raw.get("entry_point") or raw.get("entry") or "").strip()

    if not name:
        raise ValueError("module manifest requires a name")
    if not repo_url:
        raise ValueError("module manifest requires a repo URL")
    if not entry_point:
        raise ValueError("module manifest requires an entry point")

    ui_enabled = _coerce_bool(
        raw.get("ui", raw.get("ui_enabled", False)),
        field_name="ui",
    )
    cron_jobs = _parse_cron_jobs(raw.get("cron_jobs", raw.get("cron")))
    buildpacks = _parse_buildpacks(raw.get("buildpacks"))

    if not ui_enabled and not cron_jobs:
        raise ValueError("module must declare either a UI or at least one cron job")

    oauth_consumer_mode = str(raw.get("oauth_consumer_mode") or "default").strip().lower()
    if oauth_consumer_mode not in {"default", "module"}:
        raise ValueError("oauth_consumer_mode must be 'default' or 'module'")

    oauth_consumer_key_env = raw.get("oauth_consumer_key_env")
    oauth_consumer_secret_env = raw.get("oauth_consumer_secret_env")

    if oauth_consumer_mode == "module":
        oauth_consumer_key_env = str(oauth_consumer_key_env or "").strip()
        oauth_consumer_secret_env = str(oauth_consumer_secret_env or "").strip()
        if not oauth_consumer_key_env or not oauth_consumer_secret_env:
            raise ValueError(
                "module OAuth consumers require oauth_consumer_key_env and oauth_consumer_secret_env"
            )
    else:
        oauth_consumer_key_env = None
        oauth_consumer_secret_env = None

    redis_namespace = str(raw.get("redis_namespace") or "").strip() or _default_redis_namespace(name)
    title = str(raw.get("title") or "").strip() or None

    return ModuleDefinition(
        name=name,
        repo_url=repo_url,
        entry_point=entry_point,
        ui_enabled=ui_enabled,
        cron_jobs=cron_jobs,
        buildpacks=buildpacks,
        oauth_consumer_mode=oauth_consumer_mode,
        oauth_consumer_key_env=oauth_consumer_key_env,
        oauth_consumer_secret_env=oauth_consumer_secret_env,
        redis_namespace=redis_namespace,
        title=title,
    )


def load_module_definition(path: str | Path) -> ModuleDefinition:
    """Load and validate a single module manifest file."""
    manifest_path = Path(path)
    raw_manifest = _load_manifest_text(manifest_path)
    return parse_module_definition(raw_manifest)


def discover_module_manifests(root: str | Path) -> list[Path]:
    """Return manifest files under *root* in deterministic order."""
    root_path = Path(root)
    candidates: list[Path] = []
    for filename in MODULE_MANIFEST_FILENAMES:
        candidates.extend(sorted(root_path.glob(f"**/{filename}")))
    unique_candidates = {
        candidate.resolve() for candidate in candidates if candidate.is_file()
    }
    return sorted(unique_candidates)


def discover_module_definitions(root: str | Path) -> list[ModuleDefinition]:
    """Load every manifest found under *root*."""
    return [load_module_definition(path) for path in discover_module_manifests(root)]


def bootstrap_module_definitions(root: str | Path, *, enabled_default: bool = True) -> list[ModuleDefinition]:
    """Discover local module manifests and persist them to the registry.

    This is intended for bundled modules that ship with the framework repo.
    External modules can still be installed through the admin APIs.
    """
    definitions = discover_module_definitions(root)
    for definition in definitions:
        upsert_module_definition(definition, enabled=enabled_default)
    return definitions


def _serialize_manifest(definition: ModuleDefinition) -> str:
    return json.dumps(definition.as_dict(), sort_keys=True)


def _row_to_definition(row: tuple[Any, ...]) -> ModuleRecord:
    (
        _name,
        _repo_url,
        _entry_point,
        _ui_enabled,
        enabled,
        _redis_namespace,
        _oauth_consumer_mode,
        _oauth_consumer_key_env,
        _oauth_consumer_secret_env,
        manifest_json,
    ) = row

    manifest = json.loads(manifest_json)
    definition = parse_module_definition(manifest)
    return ModuleRecord(definition=definition, enabled=bool(enabled))


def upsert_module_definition(definition: ModuleDefinition, enabled: bool = False) -> None:
    """Persist or update a validated module definition."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO module_registry
                (name, repo_url, entry_point, ui_enabled, enabled, redis_namespace,
                 oauth_consumer_mode, oauth_consumer_key_env, oauth_consumer_secret_env,
                 manifest_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    repo_url=VALUES(repo_url),
                    entry_point=VALUES(entry_point),
                    ui_enabled=VALUES(ui_enabled),
                    enabled=VALUES(enabled),
                    redis_namespace=VALUES(redis_namespace),
                    oauth_consumer_mode=VALUES(oauth_consumer_mode),
                    oauth_consumer_key_env=VALUES(oauth_consumer_key_env),
                    oauth_consumer_secret_env=VALUES(oauth_consumer_secret_env),
                    manifest_json=VALUES(manifest_json)
                """,
                (
                    definition.name,
                    definition.repo_url,
                    definition.entry_point,
                    1 if definition.ui_enabled else 0,
                    1 if enabled else 0,
                    definition.redis_namespace,
                    definition.oauth_consumer_mode,
                    definition.oauth_consumer_key_env,
                    definition.oauth_consumer_secret_env,
                    _serialize_manifest(definition),
                ),
            )
            cursor.execute(
                "DELETE FROM module_cron_jobs WHERE module_name=%s",
                (definition.name,),
            )
            for cron_job in definition.cron_jobs:
                cursor.execute(
                    """
                    INSERT INTO module_cron_jobs
                    (module_name, job_name, schedule, endpoint, timeout_seconds, enabled)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        definition.name,
                        cron_job.name,
                        cron_job.schedule,
                        cron_job.endpoint,
                        cron_job.timeout_seconds,
                        1 if cron_job.enabled else 0,
                    ),
                )
        conn.commit()


def get_module_definition(name: str) -> ModuleRecord | None:
    """Return a stored module definition by name."""
    module_name = str(name or "").strip()
    if not module_name:
        return None

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT name, repo_url, entry_point, ui_enabled, enabled,
                       redis_namespace, oauth_consumer_mode,
                       oauth_consumer_key_env, oauth_consumer_secret_env,
                       manifest_json
                FROM module_registry
                WHERE name=%s
                """,
                (module_name,),
            )
            row = cursor.fetchone()

    if not row:
        return None

    return _row_to_definition(row)


def list_module_definitions(enabled_only: bool = False) -> list[ModuleRecord]:
    """Return stored module definitions from the registry."""
    query = (
        """
        SELECT name, repo_url, entry_point, ui_enabled, enabled,
               redis_namespace, oauth_consumer_mode,
               oauth_consumer_key_env, oauth_consumer_secret_env,
               manifest_json
        FROM module_registry
        """
    )
    params: tuple[Any, ...] = ()
    if enabled_only:
        query += " WHERE enabled=1"

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()

    return [_row_to_definition(row) for row in rows]


def list_module_cron_jobs(module_name: str | None = None) -> list[dict[str, Any]]:
    """Return persisted cron jobs for one module or all modules."""
    query = """
        SELECT module_name, job_name, schedule, endpoint, timeout_seconds, enabled
        FROM module_cron_jobs
    """
    params: tuple[Any, ...] = ()
    if module_name:
        query += " WHERE module_name=%s"
        params = (str(module_name).strip(),)

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()

    return [
        {
            "module_name": row[0],
            "job_name": row[1],
            "schedule": row[2],
            "endpoint": row[3],
            "timeout_seconds": int(row[4]),
            "enabled": bool(row[5]),
        }
        for row in rows
    ]


def set_module_enabled(name: str, enabled: bool) -> None:
    """Toggle a module's enabled flag."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE module_registry SET enabled=%s WHERE name=%s",
                (1 if enabled else 0, str(name).strip()),
            )
        conn.commit()


def upsert_module_access(module_name: str, username: str, enabled: bool = True) -> None:
    """Grant or revoke explicit access to a module for a username."""
    module_name = str(module_name or "").strip()
    username = str(username or "").strip().lower()
    if not module_name or not username:
        raise ValueError("module_name and username are required")

    with get_conn() as conn:
        with conn.cursor() as cursor:
            if enabled:
                cursor.execute(
                    """
                    INSERT INTO module_access (module_name, username, enabled)
                    VALUES (%s, %s, 1)
                    ON DUPLICATE KEY UPDATE enabled=1
                    """,
                    (module_name, username),
                )
            else:
                cursor.execute(
                    "DELETE FROM module_access WHERE module_name=%s AND username=%s",
                    (module_name, username),
                )
        conn.commit()


def user_has_module_access(module_name: str, username: str, *, is_maintainer: bool = False) -> bool:
    """Return True when the user may enter a module."""
    if is_maintainer:
        return True

    module_name = str(module_name or "").strip()
    username = str(username or "").strip().lower()
    if not module_name or not username:
        return False

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT enabled
                FROM module_access
                WHERE module_name=%s AND username=%s
                """,
                (module_name, username),
            )
            row = cursor.fetchone()

    return bool(row and row[0])

