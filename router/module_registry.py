"""Validate module manifests and persist the framework's module control plane.

A module starts as a JSON or TOML manifest, either stored in the repository or
advertised by an installed Python package.  This module turns that loosely
shaped input into immutable :class:`ModuleDefinition` values before any runtime
entry point, blueprint, or handler is activated.  Bootstrap then stores the
canonical manifest in ToolsDB, mirrors editable cron fields into
``module_cron_jobs``, and leaves the module's operator-controlled enabled state
intact across rediscovery.

The same registry owns the durable coordination records around module code:
explicit access grants, non-secret configuration, and queued job-run state.
It does *not* execute handlers or install repositories.  Web blueprints are
loaded by :mod:`router.module_runtime`; scheduled and manual handlers run via
``module_runner`` (with manual runs supervised by ``module_job_controller``).
Keeping import and execution out of this file makes manifest inspection and
database lifecycle operations usable without activating module code.

The SQL projections intentionally retain a compact, backward-compatible
shape.  ``manifest_json`` is authoritative for fields that have been added to
the manifest over time, while dedicated tables hold values that operators may
change at runtime.  Schema creation and additive legacy-column upgrades live
in :mod:`toolsdb`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from importlib import metadata
import json
import logging
import os
import re
import time
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
GENERATED_MODULE_RIGHTS = ("view", "estop")
LOGGER = logging.getLogger(__name__)

# Non-blank history scans may need to skip many successful no-op runs.  Bound
# and gently throttle those scans so a UI request cannot monopolize ToolsDB.
MODULE_RUN_SCAN_LIMIT_MAX = 50000
MODULE_RUN_SCAN_THROTTLE_AFTER = 1000
MODULE_RUN_SCAN_THROTTLE_SECONDS = 0.05
MODULE_RUN_CACHE_TTL_SECONDS = 86400

# These states all represent work that can conflict with a new forbid/replace
# run.  Terminal states are deliberately absent.
ACTIVE_MODULE_RUN_STATUSES = ("queued", "launching", "running", "cancel_requested")


class ModuleJobConcurrencyError(RuntimeError):
    """Report the active run ids that caused a ``forbid`` policy rejection."""

    def __init__(self, module_name: str, job_name: str, active_run_ids: list[int]):
        """Build an actionable error for one module/job concurrency conflict."""
        self.module_name = module_name
        self.job_name = job_name
        self.active_run_ids = active_run_ids
        super().__init__(
            f"Active run already exists for {module_name}/{job_name}: "
            + ", ".join(str(run_id) for run_id in active_run_ids)
        )


@dataclass(frozen=True)
class ModuleCronJob:
    """Validated schedule and execution policy for a recurring module job."""

    name: str
    schedule: str
    endpoint: str = ""
    handler: str | None = None
    schedule_text: str | None = None
    timeout_seconds: int = 300
    enabled: bool = True
    execution_mode: str = "http"
    concurrency_policy: str = "forbid"
    required_right: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-serializable cron-job representation."""
        return asdict(self)


@dataclass(frozen=True)
class ModuleWorkerJob:
    """Validated definition for a manually queued module handler."""

    name: str
    handler: str
    timeout_seconds: int = 300
    enabled: bool = True
    concurrency_policy: str = "forbid"
    required_right: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-serializable worker-job representation."""
        return asdict(self)


@dataclass(frozen=True)
class ModuleFrontend:
    """Validated resource locations and DOM integration ids for a module UI."""

    script: str
    styles: tuple[str, ...] = ()
    props_id: str = "module-ui-props"
    mount_id: str = "app"
    docs: str | None = None
    bundled: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return frontend metadata using JSON arrays instead of tuples."""
        return {
            "script": self.script,
            "styles": list(self.styles),
            "props_id": self.props_id,
            "mount_id": self.mount_id,
            "docs": self.docs,
            "bundled": self.bundled,
        }


@dataclass(frozen=True)
class ModuleDefinition:
    """Canonical, immutable module manifest consumed by framework services."""

    name: str
    repo_url: str
    entry_point: str
    ui_enabled: bool = False
    cron_jobs: tuple[ModuleCronJob, ...] = ()
    worker_jobs: tuple[ModuleWorkerJob, ...] = ()
    buildpacks: tuple[str, ...] = ()
    oauth_consumer_mode: str = "default"
    oauth_consumer_key_env: str | None = None
    oauth_consumer_secret_env: str | None = None
    redis_namespace: str | None = None
    title: str | None = None
    rights: tuple[str, ...] = ()
    frontend: ModuleFrontend | None = None
    blueprint_entry_point: str | None = None
    oauth_access_token_env: str | None = None
    oauth_access_secret_env: str | None = None

    @property
    def is_cron_only(self) -> bool:
        """Return whether the module exposes cron work but no web UI."""
        return not self.ui_enabled and bool(self.cron_jobs)

    @property
    def is_ui_enabled(self) -> bool:
        """Expose the normalized UI flag for API/template callers."""
        return bool(self.ui_enabled)

    @property
    def exposes_module_surface(self) -> bool:
        """Return whether the manifest declares any supported module surface."""
        return self.ui_enabled or bool(self.cron_jobs) or bool(self.worker_jobs)

    @property
    def has_custom_buildpacks(self) -> bool:
        """Return whether deployment metadata overrides the default build path."""
        return bool(self.buildpacks)

    @property
    def effective_rights(self) -> tuple[str, ...]:
        """Return framework-generated rights plus module-declared job rights."""
        return tuple(sorted({*GENERATED_MODULE_RIGHTS, *self.rights}))

    def as_dict(self) -> dict[str, Any]:
        """Serialize the normalized definition for APIs and ``manifest_json``."""
        payload = asdict(self)
        payload["cron_jobs"] = [job.as_dict() for job in self.cron_jobs]
        payload["worker_jobs"] = [job.as_dict() for job in self.worker_jobs]
        payload["frontend"] = self.frontend.as_dict() if self.frontend else None
        return payload


@dataclass(frozen=True)
class ModuleRecord:
    """Pair a canonical definition with its operator-controlled enabled flag."""

    definition: ModuleDefinition
    enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the definition plus registry state as an API-safe mapping."""
        payload = self.definition.as_dict()
        payload["enabled"] = bool(self.enabled)
        return payload


def _default_redis_namespace(name: str) -> str:
    """Derive a stable, Redis-key-safe namespace from a validated module name."""
    normalized = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    return normalized.strip("_") or "module"


def _normalize_module_name(raw_value: str) -> str:
    """Normalize allowlist input without claiming that it is a valid manifest name."""
    normalized = str(raw_value or "").strip().lower().replace("-", "_")
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    return normalized.strip("_")


def _validate_module_name(name: str) -> str:
    """Require the canonical lowercase identifier used in URLs, SQL, and rights."""
    normalized = _normalize_module_name(name)
    if not normalized:
        raise ValueError("module manifest requires a name")
    if normalized != name:
        raise ValueError("module name must be lowercase snake_case")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", normalized):
        raise ValueError("module name must start with a letter and contain only lowercase letters, numbers, and underscores")
    return normalized


def _validate_import_path(value: str, *, field_name: str) -> str:
    """Validate ``package.module[:attribute.path]`` without importing it.

    Importing is intentionally deferred until a module is enabled and loaded;
    manifest discovery must remain free of module-code side effects.
    """
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


def _validate_env_var_name(
    value: Any,
    *,
    field_name: str,
    required: bool = False,
) -> str | None:
    """Validate a credential variable *name* while never reading its secret."""
    cleaned = str(value or "").strip()
    if not cleaned:
        if required:
            raise ValueError(f"module OAuth consumers require {field_name}")
        return None
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", cleaned):
        raise ValueError(f"{field_name} must be an uppercase environment variable name")
    return cleaned


def _validate_resource_spec(value: Any, *, field_name: str, required: bool = False) -> str | None:
    """Validate a URL, absolute file path, or safe ``package:path`` resource."""
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
    """Decode a supported manifest file into the raw mapping validation consumes."""
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
    """Accept common manifest boolean spellings and reject ambiguous values."""
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
    """Parse a strictly positive integer, using *default* only when omitted."""
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
    """Validate recurring-job entries and infer their execution mode.

    ``run``/``schedule_text`` is the human-readable compatibility form and is
    translated to cron once at validation time.  A handler-only entry defaults
    to direct handler execution; an endpoint keeps the legacy in-app HTTP mode.
    Explicit ``execution_mode`` always wins and is checked against the resource
    it requires.
    """
    if raw_jobs in (None, ""):
        return ()
    if not isinstance(raw_jobs, list):
        raise ValueError("cron jobs must be a list")

    jobs: list[ModuleCronJob] = []
    for index, raw_job in enumerate(raw_jobs, start=1):
        if not isinstance(raw_job, dict):
            raise ValueError(f"cron job {index} must be an object")

        # ``job_id`` and ``schedule_text`` predate the canonical manifest keys;
        # accepting them keeps installed packages from breaking on bootstrap.
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
            # Endpoint jobs run through the Flask surface.  A handler with no
            # endpoint is safe to classify as direct execution automatically.
            execution_mode = "handler" if handler and not endpoint else "http"
        concurrency_policy = (
            str(raw_job.get("concurrency_policy") or "forbid").strip().lower()
        )
        required_right = _parse_job_required_right(
            raw_job.get("required_right"),
            field_name=f"cron job {index} required_right",
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
        if endpoint and not endpoint.startswith("/"):
            raise ValueError(f"cron job {index} endpoint must be an application path")
        if execution_mode not in {"http", "handler", "k8s_job"}:
            raise ValueError(
                f"cron job {index} execution_mode must be http, handler, or k8s_job"
            )
        if execution_mode == "http" and not endpoint:
            raise ValueError(f"cron job {index} execution_mode http requires endpoint")
        if execution_mode in {"handler", "k8s_job"} and not handler:
            raise ValueError(
                f"cron job {index} execution_mode {execution_mode} requires handler"
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
                required_right=required_right,
            )
        )

    return tuple(jobs)


def _parse_worker_jobs(raw_jobs: Any) -> tuple[ModuleWorkerJob, ...]:
    """Validate queue-backed handler entries from the manifest."""
    if raw_jobs in (None, ""):
        return ()
    if not isinstance(raw_jobs, list):
        raise ValueError("worker jobs must be a list")

    jobs: list[ModuleWorkerJob] = []
    for index, raw_job in enumerate(raw_jobs, start=1):
        if not isinstance(raw_job, dict):
            raise ValueError(f"worker job {index} must be an object")

        # ``job_id`` remains an accepted alias for early module packages.
        name = str(raw_job.get("name") or raw_job.get("job_id") or "").strip()
        handler = str(raw_job.get("handler") or "").strip()
        timeout_seconds = _coerce_positive_int(
            raw_job.get("timeout_seconds"),
            field_name=f"worker job {index} timeout_seconds",
            default=300,
        )
        enabled = _coerce_bool(
            raw_job.get("enabled", True),
            field_name=f"worker job {index} enabled",
        )
        concurrency_policy = (
            str(raw_job.get("concurrency_policy") or "forbid").strip().lower()
        )
        required_right = _parse_job_required_right(
            raw_job.get("required_right"),
            field_name=f"worker job {index} required_right",
        )

        if not name:
            raise ValueError(f"worker job {index} requires a name")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", name):
            raise ValueError(
                f"worker job {index} name must contain only lowercase letters, numbers, hyphens, and underscores"
            )
        if not handler:
            raise ValueError(f"worker job {index} requires a handler")
        _validate_import_path(handler, field_name=f"worker job {index} handler")
        if concurrency_policy not in {"allow", "forbid", "replace"}:
            raise ValueError(
                f"worker job {index} concurrency_policy must be allow, forbid, or replace"
            )

        jobs.append(
            ModuleWorkerJob(
                name=name,
                handler=handler,
                timeout_seconds=timeout_seconds,
                enabled=enabled,
                concurrency_policy=concurrency_policy,
                required_right=required_right,
            )
        )

    return tuple(jobs)


def _parse_job_required_right(value: Any, *, field_name: str) -> str | None:
    """Normalize an optional module-local right to lowercase snake_case."""
    cleaned = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not cleaned:
        return None
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", cleaned):
        raise ValueError(f"{field_name} must be lowercase snake_case")
    return cleaned


def _parse_buildpacks(raw_buildpacks: Any) -> tuple[str, ...]:
    """Normalize ordered, opaque deployment buildpack identifiers.

    The registry records buildpack intent but does not resolve or execute it.
    Deployment tooling owns that decision; an empty tuple means it should use
    the framework's normal build configuration.
    """
    if raw_buildpacks in (None, ""):
        return ()
    if isinstance(raw_buildpacks, str):
        raw_buildpacks = [raw_buildpacks]
    if not isinstance(raw_buildpacks, list):
        raise ValueError("buildpacks must be a list of strings")

    # Preserve author order because buildpack order can affect a platform build.
    # Values stay opaque so platform-specific URLs and short names both survive.
    buildpacks = []
    for index, raw_buildpack in enumerate(raw_buildpacks, start=1):
        buildpack = str(raw_buildpack or "").strip()
        if not buildpack:
            raise ValueError(f"buildpack {index} must be a non-empty string")
        buildpacks.append(buildpack)

    return tuple(buildpacks)


def _parse_module_rights(raw_rights: Any) -> tuple[str, ...]:
    """Return unique module-local rights, excluding framework-owned rights."""
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
        if right in GENERATED_MODULE_RIGHTS:
            # ``view`` and ``estop`` exist for every module.  Ignoring duplicate
            # declarations keeps old manifests valid without changing policy.
            LOGGER.warning(
                "Ignoring framework-generated module right '%s' in manifest",
                right,
            )
            continue
        rights.append(right)

    return tuple(sorted(set(rights)))


def _parse_frontend(raw_frontend: Any) -> ModuleFrontend | None:
    """Validate optional browser resources without opening or importing them."""
    if raw_frontend in (None, ""):
        return None
    if not isinstance(raw_frontend, dict):
        raise ValueError("frontend must be an object")

    # ``entry``/``css``/``framework_bundled`` are retained as compatibility
    # aliases; serialization always emits the canonical field names.
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
    bundled = _coerce_bool(
        raw_frontend.get("bundled", raw_frontend.get("framework_bundled", False)),
        field_name="frontend.bundled",
    )
    return ModuleFrontend(
        script=script or "",
        styles=styles,
        props_id=props_id,
        mount_id=mount_id,
        docs=docs,
        bundled=bundled,
    )


def parse_module_definition(raw: dict[str, Any]) -> ModuleDefinition:
    """Validate raw manifest data and return its canonical immutable form.

    Validation covers identifiers, import/resource syntax, supported module
    surfaces, job-name uniqueness, rights references, and OAuth variable names.
    No import, network request, secret lookup, or database write occurs here.
    """
    if not isinstance(raw, dict):
        raise ValueError("module manifest must be an object")

    # Several aliases were published during the module framework's early
    # iterations.  Read them at this boundary, then use only canonical names.
    name = _validate_module_name(str(raw.get("name") or "").strip())
    repo_url = str(raw.get("repo") or raw.get("repo_url") or "").strip()
    entry_point = _validate_import_path(
        raw.get("entry_point") or raw.get("entry"),
        field_name="entry_point",
    )
    blueprint_entry_point_raw = raw.get("blueprint_entry_point", raw.get("blueprint"))
    blueprint_entry_point = (
        _validate_import_path(
            blueprint_entry_point_raw,
            field_name="blueprint_entry_point",
        )
        if blueprint_entry_point_raw
        else None
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
    worker_jobs = _parse_worker_jobs(raw.get("worker_jobs", raw.get("queue_jobs")))
    buildpacks = _parse_buildpacks(raw.get("buildpacks"))
    rights = _parse_module_rights(
        raw.get("rights", raw.get("module_rights", raw.get("capabilities")))
    )
    frontend = _parse_frontend(raw.get("frontend", raw.get("ui_frontend")))

    if not ui_enabled and not cron_jobs and not worker_jobs:
        raise ValueError(
            "module must declare a UI, at least one cron job, or at least one worker job"
        )
    if frontend and not ui_enabled:
        raise ValueError("frontend assets require ui=true")

    # A run is addressed by (module_name, job_name), so names must be unique
    # across both execution surfaces, not merely within each manifest list.
    job_names = [job.name for job in (*cron_jobs, *worker_jobs)]
    duplicate_job_names = sorted(
        {job_name for job_name in job_names if job_names.count(job_name) > 1}
    )
    if duplicate_job_names:
        raise ValueError(
            "module job names must be unique across cron and worker jobs: "
            + ", ".join(duplicate_job_names)
        )

    # Jobs may narrow execution to a declared right, but cannot silently mint a
    # policy atom that operators never saw in the module's advertised rights.
    undeclared_job_rights = sorted(
        {
            job.required_right
            for job in (*cron_jobs, *worker_jobs)
            if job.required_right and job.required_right not in rights
        }
    )
    if undeclared_job_rights:
        raise ValueError(
            "job required_right values must also appear in module rights: "
            + ", ".join(undeclared_job_rights)
        )

    oauth_consumer_mode = str(raw.get("oauth_consumer_mode") or "default").strip().lower()
    if oauth_consumer_mode not in {"default", "module"}:
        raise ValueError("oauth_consumer_mode must be 'default' or 'module'")

    if oauth_consumer_mode == "module":
        # Store environment-variable names only.  The isolated job runner maps
        # their values into Pywikibot's expected names immediately before use.
        oauth_consumer_key_env = _validate_env_var_name(
            raw.get("oauth_consumer_key_env"),
            field_name="oauth_consumer_key_env",
            required=True,
        )
        oauth_consumer_secret_env = _validate_env_var_name(
            raw.get("oauth_consumer_secret_env"),
            field_name="oauth_consumer_secret_env",
            required=True,
        )
        oauth_access_token_env = _validate_env_var_name(
            raw.get("oauth_access_token_env") or "ACCESS_TOKEN",
            field_name="oauth_access_token_env",
            required=True,
        )
        oauth_access_secret_env = _validate_env_var_name(
            raw.get("oauth_access_secret_env") or "ACCESS_SECRET",
            field_name="oauth_access_secret_env",
            required=True,
        )
    else:
        # Default-consumer modules inherit framework credentials; discarding
        # stray names prevents a misleading half-configured credential set.
        oauth_consumer_key_env = None
        oauth_consumer_secret_env = None
        oauth_access_token_env = None
        oauth_access_secret_env = None

    redis_namespace = str(raw.get("redis_namespace") or "").strip() or _default_redis_namespace(name)
    title = str(raw.get("title") or "").strip() or None

    return ModuleDefinition(
        name=name,
        repo_url=repo_url,
        entry_point=entry_point,
        blueprint_entry_point=blueprint_entry_point,
        ui_enabled=ui_enabled,
        cron_jobs=cron_jobs,
        worker_jobs=worker_jobs,
        buildpacks=buildpacks,
        oauth_consumer_mode=oauth_consumer_mode,
        oauth_consumer_key_env=oauth_consumer_key_env,
        oauth_consumer_secret_env=oauth_consumer_secret_env,
        oauth_access_token_env=oauth_access_token_env,
        oauth_access_secret_env=oauth_access_secret_env,
        redis_namespace=redis_namespace,
        title=title,
        rights=rights,
        frontend=frontend,
    )


def load_module_definition(path: str | Path) -> ModuleDefinition:
    """Decode and validate one JSON/TOML manifest file."""
    manifest_path = Path(path)
    raw_manifest = _load_manifest_text(manifest_path)
    return parse_module_definition(raw_manifest)


def discover_module_manifests(root: str | Path) -> list[Path]:
    """Return unique manifest files below *root* in deterministic path order."""
    root_path = Path(root)
    candidates: list[Path] = []
    for filename in MODULE_MANIFEST_FILENAMES:
        candidates.extend(sorted(root_path.glob(f"**/{filename}")))
    # ``resolve`` collapses duplicate spellings/symlinks before definitions are
    # bootstrapped twice; sorting keeps startup and diagnostics reproducible.
    unique_candidates = {
        candidate.resolve() for candidate in candidates if candidate.is_file()
    }
    return sorted(unique_candidates)


def discover_module_definitions(root: str | Path) -> list[ModuleDefinition]:
    """Validate every locally discovered manifest, failing on the first error."""
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
    # Calling ``load`` imports code from an already installed package.  This is
    # only used during trusted application bootstrap, never for a remote URL
    # supplied to the registry API.
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


def _legacy_group_entry_points(entry_points: Any, group: str) -> list[Any]:
    """Read a group from the mapping returned by old ``importlib.metadata``."""
    if isinstance(entry_points, dict):
        return list(entry_points.get(group, []))
    return []


def discover_installed_module_definitions() -> list[ModuleDefinition]:
    """Load valid definitions advertised by installed Python distributions.

    One broken third-party entry point is logged and skipped so it cannot hide
    other installed modules or abort application startup.
    """
    try:
        entry_points = metadata.entry_points()
        # Python's entry-point API changed from a mapping to an EntryPoints
        # object with ``select``.  Supporting both keeps older runtime images
        # inspectable even though current production uses modern Python.
        if hasattr(entry_points, "select"):
            selected = entry_points.select(group=MODULE_ENTRY_POINT_GROUP)
        else:  # pragma: no cover - compatibility with old importlib.metadata
            selected = _legacy_group_entry_points(entry_points, MODULE_ENTRY_POINT_GROUP)
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
    """Inspect installed entry points without letting one failure abort the list.

    Each item includes its advertised name/value, a normalized definition when
    successful, or a printable error for framework diagnostics.
    """
    try:
        entry_points = metadata.entry_points()
        if hasattr(entry_points, "select"):
            selected = list(entry_points.select(group=MODULE_ENTRY_POINT_GROUP))
        else:  # pragma: no cover - compatibility with old importlib.metadata
            selected = _legacy_group_entry_points(entry_points, MODULE_ENTRY_POINT_GROUP)
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
    # Environment and file values are additive: an emergency deployment
    # override can enable a packaged module without rewriting the image.
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
            # Inline comments make the checked-in allowlist self-documenting.
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
    """Apply an optional exact-name allowlist while preserving input order."""
    if enabled_names is None:
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
    # Discovery/validation completes before the first database write, avoiding
    # a partially refreshed registry when a later local manifest is malformed.
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
    """Discover, allowlist, and persist installed-package module manifests."""
    definitions = _filter_enabled_definitions(
        discover_installed_module_definitions(),
        enabled_names,
    )
    for definition in definitions:
        upsert_module_definition(definition, enabled=enabled_default)
    return definitions


def _serialize_manifest(definition: ModuleDefinition) -> str:
    """Encode a canonical definition deterministically for ``manifest_json``."""
    return json.dumps(definition.as_dict(), sort_keys=True)


def _definition_with_cron_runtime_overrides(
    definition: ModuleDefinition,
    rows: Iterable[tuple[Any, ...]],
) -> ModuleDefinition:
    """Overlay operator-edited cron fields onto a rediscovered manifest.

    Schedules, timeouts, and per-job enabled flags are mutable runtime state.
    Rediscovery may add or remove jobs, but must not reset those fields for jobs
    that still exist.
    """
    overrides = {
        str(row[0]): row
        for row in rows
        if isinstance(row, (tuple, list)) and len(row) >= 5 and row[0]
    }
    if not overrides:
        return definition

    cron_jobs = []
    for job in definition.cron_jobs:
        row = overrides.get(job.name)
        if row is None:
            cron_jobs.append(job)
            continue
        cron_jobs.append(
            replace(
                job,
                schedule=str(row[1] or job.schedule),
                schedule_text=str(row[2]).strip() if row[2] else None,
                timeout_seconds=int(row[3] or job.timeout_seconds),
                enabled=bool(row[4]),
            )
        )
    return replace(definition, cron_jobs=tuple(cron_jobs))


def _row_to_definition(row: tuple[Any, ...]) -> ModuleRecord:
    """Rehydrate a registry row using canonical ``manifest_json`` as authority.

    The selected scalar columns remain part of the SQL projection for schema
    compatibility and operational queries.  Parsing the JSON again ensures old
    rows receive today's validation/defaults and newer manifest-only fields are
    not lost.
    """
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
    """Persist a definition and cron projection in one transaction.

    Existing cron overrides and the registry-level enabled flag are preserved.
    The *enabled* argument therefore supplies the initial insert value only; an
    operator's later toggle is never undone merely because startup rediscovered
    the module.
    """
    with get_conn() as conn:
        with conn.cursor() as cursor:
            # Read mutable job fields before replacing the cron projection, then
            # fold them into both the JSON snapshot and replacement rows.
            cursor.execute(
                """
                SELECT job_name, schedule, schedule_text, timeout_seconds, enabled
                FROM module_cron_jobs
                WHERE module_name=%s
                """,
                (definition.name,),
            )
            definition = _definition_with_cron_runtime_overrides(
                definition,
                cursor.fetchall() or (),
            )
            # The duplicate-key update intentionally omits ``enabled``.
            # Registry enablement belongs to operators, not repeatable startup.
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
            # Rebuild the cron projection so deleted manifest jobs disappear;
            # surviving jobs already carry the runtime overlays applied above.
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
    """Return one stored module record, or ``None`` for blank/unknown names."""
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
    """Return all stored records, optionally limited to enabled modules."""
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
    """Return the scheduler projection for one module or the whole registry.

    Both job-level and module-level enabled flags are returned because schedule
    generation must require both; toggling one must not erase the other.
    """
    query = """
        SELECT jobs.module_name, jobs.job_name, jobs.schedule, jobs.endpoint,
               jobs.timeout_seconds, jobs.enabled, jobs.schedule_text,
               jobs.handler, jobs.execution_mode, jobs.concurrency_policy,
               registry.enabled
        FROM module_cron_jobs AS jobs
        JOIN module_registry AS registry ON registry.name=jobs.module_name
    """
    params: tuple[Any, ...] = ()
    if module_name:
        query += " WHERE jobs.module_name=%s"
        params = (str(module_name).strip(),)

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()

    # Defaults on execution/concurrency fields keep rows created before those
    # columns were populated readable after an additive schema upgrade.
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
            "module_enabled": bool(row[10]),
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
    """Edit mutable cron fields in both SQL projections atomically.

    The dedicated cron row drives schedule generation, while ``manifest_json``
    reconstructs :class:`ModuleDefinition`.  Updating both prevents reads and
    the next bootstrap from disagreeing about operator edits.
    """
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
        # Human text is stored for display, but cron remains the executable
        # scheduler contract and is regenerated whenever that text changes.
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
        required_right=current.required_right,
    )
    cron_jobs[job_index] = updated_job

    # Rebuild the whole immutable definition so unrelated worker jobs, rights,
    # frontend data, and credential metadata survive this narrow edit.
    updated_definition = ModuleDefinition(
        name=record.definition.name,
        repo_url=record.definition.repo_url,
        entry_point=record.definition.entry_point,
        blueprint_entry_point=record.definition.blueprint_entry_point,
        ui_enabled=record.definition.ui_enabled,
        cron_jobs=tuple(cron_jobs),
        worker_jobs=record.definition.worker_jobs,
        buildpacks=record.definition.buildpacks,
        oauth_consumer_mode=record.definition.oauth_consumer_mode,
        oauth_consumer_key_env=record.definition.oauth_consumer_key_env,
        oauth_consumer_secret_env=record.definition.oauth_consumer_secret_env,
        oauth_access_token_env=record.definition.oauth_access_token_env,
        oauth_access_secret_env=record.definition.oauth_access_secret_env,
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
    concurrency_policy: str = "allow",
) -> int:
    """Create a queued run while enforcing its durable concurrency policy.

    ``allow`` always inserts.  ``forbid`` raises
    :class:`ModuleJobConcurrencyError` when active work exists.  ``replace``
    terminally cancels work that has not begun and requests cancellation from
    running work before inserting the successor.  The policy check and insert
    share one transaction so concurrent request processes reach one decision.
    """
    module_name = str(module_name or "").strip()
    job_name = str(job_name or "").strip()
    if not module_name or not job_name:
        raise ValueError("module_name and job_name are required")
    concurrency_policy = str(concurrency_policy or "allow").strip().lower()
    if concurrency_policy not in {"allow", "forbid", "replace"}:
        raise ValueError("concurrency_policy must be allow, forbid, or replace")

    payload_json = json.dumps(payload or {}, sort_keys=True)
    active_run_ids: list[int] = []
    with get_conn() as conn:
        with conn.cursor() as cursor:
            if concurrency_policy in {"forbid", "replace"}:
                # Serialize concurrency decisions on the durable module row.
                # Locking only matching run rows is insufficient when no active
                # row exists yet, because two transactions could both observe
                # an empty result before either inserts.
                cursor.execute(
                    """
                    SELECT name
                    FROM module_registry
                    WHERE name=%s
                    FOR UPDATE
                    """,
                    (module_name,),
                )
                cursor.fetchone()

                placeholders = ", ".join(["%s"] * len(ACTIVE_MODULE_RUN_STATUSES))
                cursor.execute(
                    f"""
                    SELECT id
                    FROM module_job_runs
                    WHERE module_name=%s
                      AND job_name=%s
                      AND status IN ({placeholders})
                    FOR UPDATE
                    """,
                    (
                        module_name,
                        job_name,
                        *ACTIVE_MODULE_RUN_STATUSES,
                    ),
                )
                active_run_ids = [
                    int(row[0])
                    for row in (cursor.fetchall() or ())
                    if isinstance(row, (tuple, list)) and row
                ]

            if concurrency_policy == "forbid" and active_run_ids:
                # Roll back explicitly before exposing the conflicting ids;
                # this releases the module-row lock promptly on live databases.
                conn.rollback()
                raise ModuleJobConcurrencyError(
                    module_name,
                    job_name,
                    active_run_ids,
                )

            if concurrency_policy == "replace" and active_run_ids:
                id_placeholders = ", ".join(["%s"] * len(active_run_ids))
                # Queued/launching work can become terminal immediately.  A
                # running process must observe ``cancel_requested`` and stop at
                # its controller or handler cancellation boundary.
                cursor.execute(
                    f"""
                    UPDATE module_job_runs
                    SET error=%s,
                        exit_code=CASE
                            WHEN status IN ('queued', 'launching') THEN 130
                            ELSE exit_code
                        END,
                        finished_at=CASE
                            WHEN status IN ('queued', 'launching') THEN CURRENT_TIMESTAMP
                            ELSE finished_at
                        END,
                        status=CASE
                            WHEN status IN ('queued', 'launching') THEN 'canceled'
                            ELSE 'cancel_requested'
                        END
                    WHERE id IN ({id_placeholders})
                    """,
                    (
                        "Replaced by a newer module job run",
                        *active_run_ids,
                    ),
                )

            # Insert only after the selected policy has been resolved while
            # holding the module lock; otherwise two forbid runs could race.
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
    """Return one run with JSON and timestamps decoded for framework callers."""
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
    """Claim the oldest queued run for a polling controller.

    Selection is followed by a compare-and-set update from ``queued`` to
    ``launching``.  Competing controllers may select the same id, but only one
    update succeeds; a loser returns ``None`` and polls again rather than ever
    executing a run twice.
    """
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
            # The status predicate is the ownership token.  Do not weaken this
            # to an unconditional update: it is what makes the claim atomic.
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


def claim_module_job_run(run_id: int) -> dict[str, Any] | None:
    """Atomically claim a specific queued run, returning its refreshed record.

    Celery/manual dispatch paths use this id-specific compare-and-set.  A
    ``None`` result means another owner claimed or canceled the run first.
    """
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE module_job_runs
                SET status='launching',
                    started_at=COALESCE(started_at, CURRENT_TIMESTAMP)
                WHERE id=%s AND status='queued'
                """,
                (int(run_id),),
            )
            claimed = cursor.rowcount == 1
        conn.commit()

    if not claimed:
        return None
    return get_module_job_run(int(run_id))


def update_module_job_run(
    run_id: int,
    *,
    status: str,
    error: str | None = None,
    exit_code: int | None = None,
    k8s_job_name: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    """Persist a run transition and its optional terminal metadata.

    The first launching/running transition sets ``started_at``; terminal states
    set ``finished_at``.  Optional exit/result/Kubernetes fields retain their
    previous values when omitted so independent controller and runner updates
    do not erase each other's diagnostics.
    """
    status = str(status or "").strip()
    if not status:
        raise ValueError("status is required")

    set_started = status in {"launching", "running"}
    set_finished = status in {"completed", "failed", "canceled"}
    result_json = json.dumps(result, sort_keys=True) if result is not None else None

    updated_module_name = ""
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
            cursor.execute(
                "SELECT module_name FROM module_job_runs WHERE id=%s",
                (run_id,),
            )
            row = cursor.fetchone()
            updated_module_name = str(row[0] or "") if row else ""
        conn.commit()

    # Four Award's history view filters no-op runs and is expensive to compute;
    # refresh its best-effort Redis index only after a successful terminal run.
    if status == "completed" and updated_module_name == "four_award":
        refresh_module_job_run_hit_cache(updated_module_name)


def list_module_job_runs(
    module_name: str | None = None,
    *,
    job_name: str | None = None,
    limit: int = 50,
    non_blank: bool = False,
    scan_limit: int = 1000,
) -> list[dict[str, Any]]:
    """Return recent runs, optionally filtering semantic no-op results.

    Normal history is one bounded query.  ``non_blank=True`` pages through a
    bounded scan until it finds *limit* meaningful results because older job
    result schemas do not expose a queryable SQL flag for that distinction.
    """
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
    requested_limit = max(1, min(int(limit), 1000))
    requested_scan_limit = _module_run_scan_limit(scan_limit, requested_limit)

    runs: list[dict[str, Any]] = []
    offset = 0
    with get_conn() as conn:
        while offset < requested_scan_limit:
            fetch_limit = requested_limit
            if non_blank:
                # Never scan beyond the caller's remaining cap, even when the
                # requested result count is much smaller than ``scan_limit``.
                fetch_limit = min(requested_limit, requested_scan_limit - offset)
            page_params = [*params, fetch_limit, offset]
            with conn.cursor() as cursor:
                cursor.execute(query + " ORDER BY id DESC LIMIT %s OFFSET %s", tuple(page_params))
                rows = cursor.fetchall()
            if not rows:
                break
            for row in rows:
                run = {
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
                if not non_blank or _module_run_is_non_blank(run):
                    runs.append(run)
                    if len(runs) >= requested_limit:
                        return runs
            if not non_blank or len(rows) < fetch_limit:
                break
            offset += len(rows)
            _throttle_module_run_scan(offset, requested_scan_limit)
    return runs


def _module_run_scan_limit(scan_limit: int | None, requested_limit: int) -> int:
    """Clamp a history scan while ensuring it can satisfy the requested count."""
    if scan_limit is None:
        return MODULE_RUN_SCAN_LIMIT_MAX
    return max(requested_limit, min(int(scan_limit), MODULE_RUN_SCAN_LIMIT_MAX))


def _throttle_module_run_scan(scanned: int, scan_limit: int) -> None:
    """Yield briefly during unusually deep semantic-history scans."""
    if scan_limit <= MODULE_RUN_SCAN_THROTTLE_AFTER:
        return
    if scanned < MODULE_RUN_SCAN_THROTTLE_AFTER:
        return
    time.sleep(MODULE_RUN_SCAN_THROTTLE_SECONDS)


def _module_run_is_non_blank(run: dict[str, Any]) -> bool:
    """Interpret meaningful work across current and legacy result payloads.

    Newer handlers emit ``run_kind``/``has_nominations`` explicitly.  Fallbacks
    for nomination counts and dry-run edits keep history useful for records
    written before those schema conventions existed.
    """
    result = run.get("result")
    # A failed/in-progress record without a result is still meaningful; only a
    # completed result-less record is treated as an empty success.
    if not isinstance(result, dict) or not result:
        return run.get("status") not in {"completed", "succeeded"}
    if result.get("run_kind") == "duplicate_noop":
        return False
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


def module_job_run_hit_cache_key(module_name: str) -> str:
    """Return the Redis key for one module's semantic-run history cache."""
    return f"module_runs:{module_name}:non_blank_hits"


def refresh_module_job_run_hit_cache(
    module_name: str,
    *,
    hits: int = 50,
    scan_limit: int | None = MODULE_RUN_SCAN_LIMIT_MAX,
) -> dict[str, Any]:
    """Refresh and return a best-effort cache of meaningful recent runs.

    Cache failure is logged but never changes the authoritative ToolsDB result;
    callers can still render the freshly scanned payload.
    """
    requested_hits = max(1, min(int(hits), 100))
    requested_scan_limit = _module_run_scan_limit(scan_limit, requested_hits)
    runs = list_module_job_runs(
        module_name,
        limit=requested_hits,
        non_blank=True,
        scan_limit=requested_scan_limit,
    )
    payload = {
        "module": module_name,
        "runs": runs,
        "hits": requested_hits,
        "scan_limit": requested_scan_limit,
        "returned": len(runs),
        "scan_capped": len(runs) < requested_hits,
        "refreshed_at": int(time.time()),
    }
    try:
        from redis_state import r

        r.set(
            module_job_run_hit_cache_key(module_name),
            json.dumps(payload, sort_keys=True),
            ex=MODULE_RUN_CACHE_TTL_SECONDS,
        )
    except Exception:
        LOGGER.exception("Failed to refresh module run hit cache for %s", module_name)
    return payload


def get_module_job_run_hit_cache(module_name: str) -> dict[str, Any] | None:
    """Return a valid cached history mapping, or ``None`` on miss/corruption."""
    try:
        from redis_state import r

        raw = r.get(module_job_run_hit_cache_key(module_name))
        if not raw:
            return None
        payload = json.loads(raw)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def request_module_job_run_cancel(run_id: int) -> None:
    """Record cooperative cancellation for one active run.

    Queued work becomes terminal immediately with shell-style exit code 130.
    Launching/running work moves to ``cancel_requested`` so its execution owner
    can terminate the process and record the final ``canceled`` transition.
    """
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE module_job_runs
                SET error=%s,
                    exit_code=CASE WHEN status='queued' THEN 130 ELSE exit_code END,
                    finished_at=CASE
                        WHEN status='queued' THEN CURRENT_TIMESTAMP
                        ELSE finished_at
                    END,
                    status=CASE
                        WHEN status='queued' THEN 'canceled'
                        ELSE 'cancel_requested'
                    END
                WHERE id=%s AND status IN ('queued', 'launching', 'running')
                """,
                ("Cancellation requested from web UI", run_id),
            )
        conn.commit()


def request_module_job_runs_cancel(module_name: str) -> list[dict[str, Any]]:
    """Terminally cancel all active rows for a module emergency stop.

    Unlike one-run cooperative cancellation, emergency stop records every row
    as terminal immediately.  The caller (:mod:`router.module_estop`) separately
    kills framework and platform processes, so the returned pre-update records
    identify which external work still needs cleanup.
    """
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
            # Capture identifiers before the update so the e-stop orchestrator
            # can still locate any Kubernetes/Toolforge work it must terminate.
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
    """Return decoded, non-secret runtime configuration for one module.

    Current writes use JSON.  The ``value_type`` branch preserves compatibility
    with older text rows, and malformed legacy JSON is returned verbatim rather
    than making all module configuration unreadable.
    """
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
                # Be liberal when reading old/manual rows; a later PUT will
                # rewrite the value using the canonical JSON representation.
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
    """Upsert non-secret module settings as canonical JSON values.

    Callers must keep credentials in environment-backed manifest fields.  This
    table is intended for operator-editable behavior such as dry-run flags,
    limits, and page names; ``updated_by`` provides the audit attribution.
    """
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
                    # Ignore an unusable key rather than writing a row that no
                    # caller can address consistently.
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
    """Set the operator-controlled registry enablement flag for one module."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE module_registry SET enabled=%s WHERE name=%s",
                (1 if enabled else 0, str(name).strip()),
            )
        conn.commit()


def upsert_module_access(module_name: str, username: str, enabled: bool = True) -> None:
    """Grant or revoke a case-insensitive legacy explicit-access row.

    New policy can grant module rights through :mod:`router.authz`; this table
    remains a supported direct grant source for existing deployments and the
    module-access management API.
    """
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
    """Resolve module entry access across maintainer, authz, and legacy grants.

    Maintainers bypass module-specific checks.  Other users receive access from
    either the canonical ``module:<name>:access``/``view`` rights or an enabled
    ``module_access`` row.  Authz lookup failures fall through to the durable
    explicit table so a transient policy/cache problem does not erase existing
    grants.
    """
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
        if user_has_module_right(username, module_name, "view"):
            return True
    except Exception:
        # Preserve the independent legacy access path when authz configuration
        # or its backing services are temporarily unavailable.
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
