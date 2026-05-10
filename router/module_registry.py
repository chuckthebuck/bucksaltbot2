"""Module manifest parsing and registry helpers.

This is the first step toward a module-first framework: a module must be
declared by a manifest, must expose either a UI or cron surface, and may opt
into its own OAuth consumer instead of the framework default worker consumer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import metadata
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable

from toolsdb import get_conn
from router.module_schedule import human_schedule_to_cron

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None  # type: ignore[assignment]


MODULE_MANIFEST_FILENAMES = ("module.toml", "module.json")
MODULE_ENTRY_POINT_GROUP = "chuck_buckbot.modules"
ENABLED_MODULES_FILENAME = "enabled-modules.txt"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleCronJob:
    """Declarative cron job entry from a module manifest."""

    name: str
    schedule: str
    endpoint: str = ""
    handler: str | None = None
    schedule_text: str | None = None
    timeout_seconds: int = 300
    enabled: bool = True
    execution_mode: str = "http"
    concurrency_policy: str = "forbid"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModuleFrontend:
    """Packaged browser assets for a module-owned UI."""

    script: str
    styles: tuple[str, ...] = ()
    props_id: str = "module-ui-props"
    mount_id: str = "app"
    docs: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "script": self.script,
            "styles": list(self.styles),
            "props_id": self.props_id,
            "mount_id": self.mount_id,
            "docs": self.docs,
        }


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
    rights: tuple[str, ...] = ()
    frontend: ModuleFrontend | None = None

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
        payload["frontend"] = self.frontend.as_dict() if self.frontend else None
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


def _normalize_module_name(raw_value: str) -> str:
    normalized = str(raw_value or "").strip().lower().replace("-", "_")
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    return normalized.strip("_")


def _validate_module_name(name: str) -> str:
    normalized = _normalize_module_name(name)
    if not normalized:
        raise ValueError("module manifest requires a name")
    if normalized != name:
        raise ValueError("module name must be lowercase snake_case")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", normalized):
        raise ValueError("module name must start with a letter and contain only lowercase letters, numbers, and underscores")
    return normalized


def _validate_import_path(value: str, *, field_name: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"module manifest requires {field_name}")
    if cleaned.endswith(".py"):
        raise ValueError(f"{field_name} must start with a Python dotted import path")
    module_part, _, attr_part = cleaned.partition(":")
    identifier = r"[A-Za-z_][A-Za-z0-9_]*"
    dotted = rf"{identifier}(?:\.{identifier})*"
    if not re.fullmatch(dotted, module_part):
        raise ValueError(f"{field_name} must start with a Python dotted import path")
    if attr_part and not re.fullmatch(dotted, attr_part):
        raise ValueError(f"{field_name} attribute path is invalid")
    return cleaned


def _validate_resource_spec(value: Any, *, field_name: str, required: bool = False) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    if cleaned.startswith(("/", "http://", "https://")):
        return cleaned
    package, sep, resource_path = cleaned.partition(":")
    if not sep:
        raise ValueError(f"{field_name} must be a URL, absolute path, or package:path resource")
    _validate_import_path(package, field_name=field_name)
    if not resource_path or resource_path.startswith("/") or ".." in Path(resource_path).parts:
        raise ValueError(f"{field_name} package resource path is invalid")
    return cleaned


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
        schedule_text = str(
            raw_job.get("run") or raw_job.get("schedule_text") or ""
        ).strip()
        schedule = str(raw_job.get("schedule") or "").strip()
        if not schedule and schedule_text:
            schedule = human_schedule_to_cron(schedule_text)
        endpoint = str(raw_job.get("endpoint") or "").strip()
        handler = str(raw_job.get("handler") or "").strip() or None
        execution_mode = str(raw_job.get("execution_mode") or "").strip().lower()
        if not execution_mode:
            execution_mode = "handler" if handler and not endpoint else "http"
        concurrency_policy = (
            str(raw_job.get("concurrency_policy") or "forbid").strip().lower()
        )
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
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", name):
            raise ValueError(
                f"cron job {index} name must contain only lowercase letters, numbers, hyphens, and underscores"
            )
        if not schedule:
            raise ValueError(f"cron job {index} requires a schedule or run")
        if not endpoint and not handler:
            raise ValueError(f"cron job {index} requires an endpoint or handler")
        if handler:
            _validate_import_path(handler, field_name=f"cron job {index} handler")
        if endpoint and not endpoint.startswith(("/", "http://", "https://")):
            raise ValueError(f"cron job {index} endpoint must be a path or URL")
        if execution_mode not in {"http", "handler", "k8s_job"}:
            raise ValueError(
                f"cron job {index} execution_mode must be http, handler, or k8s_job"
            )
        if concurrency_policy not in {"allow", "forbid", "replace"}:
            raise ValueError(
                f"cron job {index} concurrency_policy must be allow, forbid, or replace"
            )

        jobs.append(
            ModuleCronJob(
                name=name,
                schedule=schedule,
                endpoint=endpoint,
                handler=handler,
                schedule_text=schedule_text or None,
                timeout_seconds=timeout_seconds,
                enabled=enabled,
                execution_mode=execution_mode,
                concurrency_policy=concurrency_policy,
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


def _parse_module_rights(raw_rights: Any) -> tuple[str, ...]:
    if raw_rights in (None, ""):
        return ()
    if isinstance(raw_rights, str):
        raw_rights = [raw_rights]
    if not isinstance(raw_rights, list):
        raise ValueError("rights must be a list of module right strings")

    rights = []
    for index, raw_right in enumerate(raw_rights, start=1):
        right = str(raw_right or "").strip().lower().replace(" ", "_").replace("-", "_")
        if not right:
            raise ValueError(f"right {index} must be a non-empty string")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", right):
            raise ValueError(
                f"right {index} must be lowercase snake_case and must not contain ':'"
            )
        rights.append(right)

    return tuple(sorted(set(rights)))


def _parse_frontend(raw_frontend: Any) -> ModuleFrontend | None:
    if raw_frontend in (None, ""):
        return None
    if not isinstance(raw_frontend, dict):
        raise ValueError("frontend must be an object")

    script = _validate_resource_spec(
        raw_frontend.get("script") or raw_frontend.get("entry"),
        field_name="frontend.script",
        required=True,
    )
    styles_raw = raw_frontend.get("styles", raw_frontend.get("css", []))
    if styles_raw in (None, ""):
        styles_raw = []
    if isinstance(styles_raw, str):
        styles_raw = [styles_raw]
    if not isinstance(styles_raw, list):
        raise ValueError("frontend.styles must be a list of resource specs")
    styles = tuple(
        value
        for value in (
            _validate_resource_spec(style, field_name=f"frontend.styles[{index}]")
            for index, style in enumerate(styles_raw, start=1)
        )
        if value
    )

    props_id = str(raw_frontend.get("props_id") or "module-ui-props").strip()
    mount_id = str(raw_frontend.get("mount_id") or "app").strip()
    for field_name, value in (("frontend.props_id", props_id), ("frontend.mount_id", mount_id)):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value):
            raise ValueError(f"{field_name} must be a valid DOM id")

    docs = _validate_resource_spec(raw_frontend.get("docs"), field_name="frontend.docs")
    return ModuleFrontend(
        script=script or "",
        styles=styles,
        props_id=props_id,
        mount_id=mount_id,
        docs=docs,
    )


def parse_module_definition(raw: dict[str, Any]) -> ModuleDefinition:
    """Validate and normalize a module manifest dictionary."""
    if not isinstance(raw, dict):
        raise ValueError("module manifest must be an object")

    name = _validate_module_name(str(raw.get("name") or "").strip())
    repo_url = str(raw.get("repo") or raw.get("repo_url") or "").strip()
    entry_point = _validate_import_path(
        raw.get("entry_point") or raw.get("entry"),
        field_name="entry_point",
    )

    if not repo_url:
        raise ValueError("module manifest requires a repo URL")
    if not repo_url.startswith(("https://", "http://", "git+https://", "ssh://", "git@")):
        raise ValueError("repo URL must be an explicit git or HTTP(S) URL")

    ui_enabled = _coerce_bool(
        raw.get("ui", raw.get("ui_enabled", False)),
        field_name="ui",
    )
    cron_jobs = _parse_cron_jobs(raw.get("jobs", raw.get("cron_jobs", raw.get("cron"))))
    buildpacks = _parse_buildpacks(raw.get("buildpacks"))
    rights = _parse_module_rights(
        raw.get("rights", raw.get("module_rights", raw.get("capabilities")))
    )
    frontend = _parse_frontend(raw.get("frontend", raw.get("ui_frontend")))

    if not ui_enabled and not cron_jobs:
        raise ValueError("module must declare either a UI or at least one cron job")
    if frontend and not ui_enabled:
        raise ValueError("frontend assets require ui=true")

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
        rights=rights,
        frontend=frontend,
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


def _definition_from_package_entry_point(entry_point) -> ModuleDefinition:
    """Load a module definition advertised by an installed Python package.

    Packages can expose an entry point in the ``chuck_buckbot.modules`` group.
    The entry point may resolve to:

    - a manifest dict
    - a callable returning a manifest dict
    - a path string pointing at a TOML/JSON manifest
    - a ModuleDefinition
    """
    loaded = entry_point.load()
    value = loaded() if callable(loaded) else loaded

    if isinstance(value, ModuleDefinition):
        return value
    if isinstance(value, dict):
        return parse_module_definition(value)
    if isinstance(value, (str, Path)):
        return load_module_definition(value)

    raise ValueError(
        f"Module entry point {entry_point.name} returned unsupported value "
        f"{type(value).__name__}"
    )


def discover_installed_module_definitions() -> list[ModuleDefinition]:
    """Discover module definitions exposed by installed Python packages."""
    try:
        entry_points = metadata.entry_points()
        if hasattr(entry_points, "select"):
            selected = entry_points.select(group=MODULE_ENTRY_POINT_GROUP)
        else:  # pragma: no cover - compatibility with old importlib.metadata
            selected = entry_points.get(MODULE_ENTRY_POINT_GROUP, [])
    except Exception:
        LOGGER.exception("Failed to read Python package entry points")
        return []

    definitions: list[ModuleDefinition] = []
    for entry_point in selected:
        try:
            definitions.append(_definition_from_package_entry_point(entry_point))
        except Exception:
            LOGGER.exception(
                "Failed to load module entry point %s from %s",
                getattr(entry_point, "name", "<unknown>"),
                getattr(entry_point, "value", "<unknown>"),
            )
            continue
    return definitions


def inspect_installed_module_entry_points() -> list[dict[str, Any]]:
    """Return diagnostic info for installed module package entry points."""
    try:
        entry_points = metadata.entry_points()
        if hasattr(entry_points, "select"):
            selected = list(entry_points.select(group=MODULE_ENTRY_POINT_GROUP))
        else:  # pragma: no cover - compatibility with old importlib.metadata
            selected = list(entry_points.get(MODULE_ENTRY_POINT_GROUP, []))
    except Exception as exc:
        return [
            {
                "ok": False,
                "name": None,
                "value": None,
                "definition": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
        ]

    diagnostics: list[dict[str, Any]] = []
    for entry_point in selected:
        item: dict[str, Any] = {
            "ok": False,
            "name": getattr(entry_point, "name", None),
            "value": getattr(entry_point, "value", None),
            "definition": None,
            "error": None,
        }
        try:
            definition = _definition_from_package_entry_point(entry_point)
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
        else:
            item["ok"] = True
            item["definition"] = definition.as_dict()
        diagnostics.append(item)
    return diagnostics


def load_enabled_module_names(path: str | Path | None = None) -> set[str]:
    """Return the explicitly enabled module names for this framework build.

    Production deploys should keep this list tiny and boring. Module packages
    are installed by ``requirements-modules.txt``; this file says which
    installed package manifests the framework should register.
    """
    raw_names: list[str] = []
    env_value = os.getenv("ENABLED_MODULES", "").strip()
    if env_value:
        raw_names.extend(env_value.split(","))

    config_path = (
        Path(path)
        if path is not None
        else Path(__file__).resolve().parent.parent / ENABLED_MODULES_FILENAME
    )
    try:
        for raw_line in config_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if line:
                raw_names.append(line)
    except OSError:
        pass

    names: set[str] = set()
    for raw_name in raw_names:
        name = _normalize_module_name(str(raw_name).strip())
        if name:
            names.add(name)
    return names


def _filter_enabled_definitions(
    definitions: Iterable[ModuleDefinition],
    enabled_names: set[str] | None,
) -> list[ModuleDefinition]:
    if not enabled_names:
        return list(definitions)
    return [
        definition
        for definition in definitions
        if definition.name in enabled_names
    ]


def bootstrap_module_definitions(
    root: str | Path,
    *,
    enabled_default: bool = True,
    enabled_names: set[str] | None = None,
) -> list[ModuleDefinition]:
    """Discover local module manifests and persist them to the registry.

    This is intended for modules that ship with the framework repo. External
    module repos should be vendored into the repo and installed from
    ``requirements-modules.txt`` during build.
    """
    definitions = _filter_enabled_definitions(
        discover_module_definitions(root),
        enabled_names,
    )
    for definition in definitions:
        upsert_module_definition(definition, enabled=enabled_default)
    return definitions


def bootstrap_installed_module_definitions(
    *,
    enabled_default: bool = True,
    enabled_names: set[str] | None = None,
) -> list[ModuleDefinition]:
    """Persist module manifests advertised by installed Python packages."""
    definitions = _filter_enabled_definitions(
        discover_installed_module_definitions(),
        enabled_names,
    )
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
                    (
                        module_name,
                        job_name,
                        schedule,
                        schedule_text,
                        endpoint,
                        handler,
                        execution_mode,
                        concurrency_policy,
                        timeout_seconds,
                        enabled
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        definition.name,
                        cron_job.name,
                        cron_job.schedule,
                        cron_job.schedule_text,
                        cron_job.endpoint,
                        cron_job.handler,
                        cron_job.execution_mode,
                        cron_job.concurrency_policy,
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
        SELECT module_name, job_name, schedule, endpoint, timeout_seconds, enabled,
               schedule_text, handler, execution_mode, concurrency_policy
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
            "schedule_text": row[6],
            "handler": row[7],
            "execution_mode": row[8] or "http",
            "concurrency_policy": row[9] or "forbid",
        }
        for row in rows
    ]


def update_module_cron_job(
    module_name: str,
    job_name: str,
    *,
    schedule_text: str | None = None,
    schedule: str | None = None,
    timeout_seconds: int | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Update a persisted module job schedule and keep manifest JSON in sync."""
    module_name = str(module_name or "").strip()
    job_name = str(job_name or "").strip()
    if not module_name or not job_name:
        raise ValueError("module_name and job_name are required")

    record = get_module_definition(module_name)
    if record is None:
        raise ValueError("Module not found")

    cron_jobs = list(record.definition.cron_jobs)
    job_index = next((i for i, job in enumerate(cron_jobs) if job.name == job_name), None)
    if job_index is None:
        raise ValueError("Job not found")

    current = cron_jobs[job_index]
    new_schedule_text = current.schedule_text
    new_schedule = current.schedule

    if schedule_text is not None:
        new_schedule_text = str(schedule_text or "").strip() or None
        if new_schedule_text:
            new_schedule = human_schedule_to_cron(new_schedule_text)
        elif schedule is None:
            raise ValueError("schedule_text cannot be empty without schedule")

    if schedule is not None:
        new_schedule = str(schedule or "").strip()
        if not new_schedule:
            raise ValueError("schedule cannot be empty")

    new_timeout_seconds = current.timeout_seconds
    if timeout_seconds is not None:
        new_timeout_seconds = _coerce_positive_int(
            timeout_seconds,
            field_name="timeout_seconds",
            default=current.timeout_seconds,
        )

    new_enabled = current.enabled if enabled is None else bool(enabled)

    updated_job = ModuleCronJob(
        name=current.name,
        schedule=new_schedule,
        endpoint=current.endpoint,
        handler=current.handler,
        schedule_text=new_schedule_text,
        timeout_seconds=new_timeout_seconds,
        enabled=new_enabled,
        execution_mode=current.execution_mode,
        concurrency_policy=current.concurrency_policy,
    )
    cron_jobs[job_index] = updated_job

    updated_definition = ModuleDefinition(
        name=record.definition.name,
        repo_url=record.definition.repo_url,
        entry_point=record.definition.entry_point,
        ui_enabled=record.definition.ui_enabled,
        cron_jobs=tuple(cron_jobs),
        buildpacks=record.definition.buildpacks,
        oauth_consumer_mode=record.definition.oauth_consumer_mode,
        oauth_consumer_key_env=record.definition.oauth_consumer_key_env,
        oauth_consumer_secret_env=record.definition.oauth_consumer_secret_env,
        redis_namespace=record.definition.redis_namespace,
        title=record.definition.title,
        rights=record.definition.rights,
        frontend=record.definition.frontend,
    )

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE module_cron_jobs
                SET schedule=%s,
                    schedule_text=%s,
                    timeout_seconds=%s,
                    enabled=%s
                WHERE module_name=%s AND job_name=%s
                """,
                (
                    updated_job.schedule,
                    updated_job.schedule_text,
                    updated_job.timeout_seconds,
                    1 if updated_job.enabled else 0,
                    module_name,
                    job_name,
                ),
            )
            cursor.execute(
                """
                UPDATE module_registry
                SET manifest_json=%s
                WHERE name=%s
                """,
                (_serialize_manifest(updated_definition), module_name),
            )
        conn.commit()

    return {
        "module_name": module_name,
        "job_name": updated_job.name,
        "schedule": updated_job.schedule,
        "endpoint": updated_job.endpoint,
        "timeout_seconds": updated_job.timeout_seconds,
        "enabled": updated_job.enabled,
        "schedule_text": updated_job.schedule_text,
        "handler": updated_job.handler,
        "execution_mode": updated_job.execution_mode,
        "concurrency_policy": updated_job.concurrency_policy,
    }


def create_module_job_run(
    module_name: str,
    job_name: str,
    *,
    trigger_type: str = "manual",
    triggered_by: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """Create a tracked run row for a managed module job."""
    module_name = str(module_name or "").strip()
    job_name = str(job_name or "").strip()
    if not module_name or not job_name:
        raise ValueError("module_name and job_name are required")

    payload_json = json.dumps(payload or {}, sort_keys=True)
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO module_job_runs
                (
                    module_name,
                    job_name,
                    status,
                    trigger_type,
                    triggered_by,
                    payload_json
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    module_name,
                    job_name,
                    "queued",
                    str(trigger_type or "manual").strip() or "manual",
                    triggered_by,
                    payload_json,
                ),
            )
            run_id = int(cursor.lastrowid)
        conn.commit()
    return run_id


def get_module_job_run(run_id: int) -> dict[str, Any] | None:
    """Return one tracked module job run by id."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, module_name, job_name, status, trigger_type, triggered_by,
                       k8s_job_name, started_at, finished_at, exit_code, error,
                       payload_json, result_json, created_at
                FROM module_job_runs
                WHERE id=%s
                """,
                (run_id,),
            )
            row = cursor.fetchone()

    if not row:
        return None

    return {
        "id": int(row[0]),
        "module_name": row[1],
        "job_name": row[2],
        "status": row[3],
        "trigger_type": row[4],
        "triggered_by": row[5],
        "k8s_job_name": row[6],
        "started_at": str(row[7]) if row[7] is not None else None,
        "finished_at": str(row[8]) if row[8] is not None else None,
        "exit_code": row[9],
        "error": row[10],
        "payload": json.loads(row[11] or "{}"),
        "result": json.loads(row[12] or "{}"),
        "created_at": str(row[13]) if row[13] is not None else None,
    }


def claim_next_queued_module_job_run() -> dict[str, Any] | None:
    """Claim one queued manual/module run for the local controller."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM module_job_runs
                WHERE status='queued'
                ORDER BY id ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if not row:
                return None

            run_id = int(row[0])
            cursor.execute(
                """
                UPDATE module_job_runs
                SET status='launching'
                WHERE id=%s AND status='queued'
                """,
                (run_id,),
            )
            if cursor.rowcount != 1:
                conn.commit()
                return None
        conn.commit()

    return get_module_job_run(run_id)


def update_module_job_run(
    run_id: int,
    *,
    status: str,
    error: str | None = None,
    exit_code: int | None = None,
    k8s_job_name: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    """Update lifecycle state for a tracked module job run."""
    status = str(status or "").strip()
    if not status:
        raise ValueError("status is required")

    set_started = status in {"launching", "running"}
    set_finished = status in {"completed", "failed", "canceled"}
    result_json = json.dumps(result, sort_keys=True) if result is not None else None

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE module_job_runs
                SET status=%s,
                    error=%s,
                    exit_code=COALESCE(%s, exit_code),
                    k8s_job_name=COALESCE(%s, k8s_job_name),
                    result_json=COALESCE(%s, result_json),
                    started_at=CASE
                        WHEN %s=1 AND started_at IS NULL THEN CURRENT_TIMESTAMP
                        ELSE started_at
                    END,
                    finished_at=CASE
                        WHEN %s=1 THEN CURRENT_TIMESTAMP
                        ELSE finished_at
                    END
                WHERE id=%s
                """,
                (
                    status,
                    error,
                    exit_code,
                    k8s_job_name,
                    result_json,
                    1 if set_started else 0,
                    1 if set_finished else 0,
                    run_id,
                ),
            )
        conn.commit()


def list_module_job_runs(
    module_name: str | None = None,
    *,
    job_name: str | None = None,
    limit: int = 50,
    non_blank: bool = False,
) -> list[dict[str, Any]]:
    """Return recent tracked runs for managed module jobs."""
    conditions = []
    params: list[Any] = []
    if module_name:
        conditions.append("module_name=%s")
        params.append(str(module_name).strip())
    if job_name:
        conditions.append("job_name=%s")
        params.append(str(job_name).strip())

    query = """
        SELECT id, module_name, job_name, status, trigger_type, triggered_by,
               k8s_job_name, started_at, finished_at, exit_code, error,
               payload_json, result_json, created_at
        FROM module_job_runs
    """
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id DESC LIMIT %s"
    requested_limit = max(1, min(int(limit), 200))
    fetch_limit = min(1000, max(requested_limit, requested_limit * 10)) if non_blank else requested_limit
    params.append(fetch_limit)

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

    runs = [
        {
            "id": int(row[0]),
            "module_name": row[1],
            "job_name": row[2],
            "status": row[3],
            "trigger_type": row[4],
            "triggered_by": row[5],
            "k8s_job_name": row[6],
            "started_at": str(row[7]) if row[7] is not None else None,
            "finished_at": str(row[8]) if row[8] is not None else None,
            "exit_code": row[9],
            "error": row[10],
            "payload": json.loads(row[11] or "{}"),
            "result": json.loads(row[12] or "{}"),
            "created_at": str(row[13]) if row[13] is not None else None,
        }
        for row in rows
    ]
    if non_blank:
        runs = [run for run in runs if _module_run_is_non_blank(run)]
    return runs[:requested_limit]


def _module_run_is_non_blank(run: dict[str, Any]) -> bool:
    result = run.get("result")
    if not isinstance(result, dict) or not result:
        return run.get("status") not in {"completed", "succeeded"}
    if result.get("has_nominations") is True:
        return True
    try:
        if int(result.get("nomination_count") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    edits = result.get("dry_run_edits")
    if isinstance(edits, list) and edits:
        return True
    return result.get("run_kind") != "empty" and result.get("has_nominations") is not False


def request_module_job_run_cancel(run_id: int) -> None:
    """Mark a queued/running module run as cancel requested."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE module_job_runs
                SET status=%s, error=%s
                WHERE id=%s AND status IN ('queued', 'running')
                """,
                ("cancel_requested", "Cancellation requested from web UI", run_id),
            )
        conn.commit()


def request_module_job_runs_cancel(module_name: str) -> list[dict[str, Any]]:
    """Mark every active run for a module as canceled by an emergency stop."""
    module_name = str(module_name or "").strip()
    if not module_name:
        return []

    active_statuses = ("queued", "launching", "running", "cancel_requested")
    placeholders = ", ".join(["%s"] * len(active_statuses))

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, module_name, job_name, status, trigger_type, triggered_by,
                       k8s_job_name, started_at, finished_at, exit_code, error,
                       payload_json, result_json, created_at
                FROM module_job_runs
                WHERE module_name=%s AND status IN ({placeholders})
                ORDER BY id DESC
                """,
                (module_name, *active_statuses),
            )
            rows = cursor.fetchall()
            cursor.execute(
                f"""
                UPDATE module_job_runs
                SET status=%s,
                    error=%s,
                    exit_code=COALESCE(exit_code, %s),
                    finished_at=CURRENT_TIMESTAMP
                WHERE module_name=%s AND status IN ({placeholders})
                """,
                (
                    "canceled",
                    "Module emergency stop requested from web UI",
                    130,
                    module_name,
                    *active_statuses,
                ),
            )
        conn.commit()

    return [
        {
            "id": int(row[0]),
            "module_name": row[1],
            "job_name": row[2],
            "status": row[3],
            "trigger_type": row[4],
            "triggered_by": row[5],
            "k8s_job_name": row[6],
            "started_at": str(row[7]) if row[7] is not None else None,
            "finished_at": str(row[8]) if row[8] is not None else None,
            "exit_code": row[9],
            "error": row[10],
            "payload": json.loads(row[11] or "{}"),
            "result": json.loads(row[12] or "{}"),
            "created_at": str(row[13]) if row[13] is not None else None,
        }
        for row in rows
    ]


def get_module_config(module_name: str) -> dict[str, Any]:
    """Return DB-backed non-secret config for a module."""
    module_name = str(module_name or "").strip()
    if not module_name:
        return {}

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT config_key, config_value, value_type
                FROM module_config
                WHERE module_name=%s
                """,
                (module_name,),
            )
            rows = cursor.fetchall()

    config: dict[str, Any] = {}
    for key, raw_value, value_type in rows:
        if value_type == "json":
            try:
                config[str(key)] = json.loads(raw_value)
            except (TypeError, json.JSONDecodeError):
                config[str(key)] = raw_value
        else:
            config[str(key)] = raw_value
    return config


def upsert_module_config(
    module_name: str,
    updates: dict[str, Any],
    *,
    updated_by: str | None = None,
) -> None:
    """Persist DB-backed non-secret config for a module."""
    module_name = str(module_name or "").strip()
    if not module_name:
        raise ValueError("module_name is required")
    if not isinstance(updates, dict):
        raise ValueError("updates must be a dictionary")

    with get_conn() as conn:
        with conn.cursor() as cursor:
            for key, value in updates.items():
                config_key = str(key or "").strip()
                if not config_key:
                    continue
                cursor.execute(
                    """
                    INSERT INTO module_config
                    (
                        module_name,
                        config_key,
                        config_value,
                        value_type,
                        updated_by
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        config_value=VALUES(config_value),
                        value_type=VALUES(value_type),
                        updated_by=VALUES(updated_by)
                    """,
                    (
                        module_name,
                        config_key,
                        json.dumps(value, sort_keys=True),
                        "json",
                        updated_by,
                    ),
                )
        conn.commit()


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

    try:
        from router.authz import user_has_module_right

        if user_has_module_right(username, module_name, "access"):
            return True
    except Exception:
        pass

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
