"""Buckbot framework self-test checks.

The checks in this module are intentionally lightweight by default: they prove
the repository, Python package environment, enabled modules, handlers, and
packaged assets agree with each other without requiring Toolforge services.
Service checks can be enabled separately for local full-stack or Toolforge
startup probes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
import importlib.util
from importlib import resources
import json
import os
from pathlib import Path
import sys
import tomllib
from types import ModuleType
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent
FATAL = "fatal"
DEGRADED = "degraded"
WARNING = "warning"
OK = "ok"


@dataclass(frozen=True)
class SelfTestCheck:
    """One named probe with severity, outcome, message, and optional evidence."""

    name: str
    severity: str
    ok: bool
    message: str
    detail: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the machine-readable representation of this probe."""
        payload = {
            "name": self.name,
            "severity": self.severity,
            "ok": self.ok,
            "message": self.message,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass(frozen=True)
class SelfTestResult:
    """Ordered collection of probes with aggregate status and exit policy."""

    checks: tuple[SelfTestCheck, ...]

    @property
    def status(self) -> str:
        """Return the highest failed severity, or ``ok`` when all pass."""
        if any(not check.ok and check.severity == FATAL for check in self.checks):
            return FATAL
        if any(not check.ok and check.severity == DEGRADED for check in self.checks):
            return DEGRADED
        if any(not check.ok and check.severity == WARNING for check in self.checks):
            return WARNING
        return OK

    def exit_code(self, *, strict: bool = False) -> int:
        """Map aggregate status to a process exit code under the chosen policy."""
        if self.status == FATAL:
            return 1
        if strict and self.status in {DEGRADED, WARNING}:
            return 1
        return 0

    def as_dict(self) -> dict[str, Any]:
        """Return the complete machine-readable self-test report."""
        return {
            "status": self.status,
            "checks": [check.as_dict() for check in self.checks],
        }


def _check(name: str, severity: str, ok: bool, message: str, **detail: Any) -> SelfTestCheck:
    """Build a check while dropping absent evidence fields."""
    return SelfTestCheck(
        name=name,
        severity=severity,
        ok=ok,
        message=message,
        detail={key: value for key, value in detail.items() if value is not None} or None,
    )


def _import_dependencies() -> SelfTestCheck:
    """Verify that every framework runtime dependency is import-resolvable."""
    required = (
        "celery",
        "flask",
        "mwoauth",
        "pymysql",
        "pywikibot",
        "redis",
        "requests",
    )
    missing: list[str] = []
    for module_name in required:
        # find_spec avoids package import side effects such as network/config
        # initialization while still catching missing dependency trees.
        try:
            available = importlib.util.find_spec(module_name) is not None
        except (ModuleNotFoundError, ValueError):
            available = False
        if not available:
            missing.append(module_name)

    return _check(
        "python_dependencies",
        FATAL,
        not missing,
        "Required Python dependencies are importable"
        if not missing
        else "Missing required Python dependencies: " + ", ".join(missing),
        missing=missing,
    )


def _load_module_definitions():
    """Discover enabled, local, and vendored module definitions for probes."""
    os.environ.setdefault("NOTDEV", "1")
    os.environ.setdefault("ENABLE_MODULE_LOADING", "0")
    _add_vendored_source_roots()

    from router.module_registry import (
        discover_module_definitions,
        discover_module_manifests,
        load_module_definition,
        load_enabled_module_names,
    )

    enabled = load_enabled_module_names()
    local = {definition.name: definition for definition in discover_module_definitions(REPO_ROOT / "modules")}
    vendored = {}
    vendor_root = REPO_ROOT / "vendor" / "modules"
    if vendor_root.exists():
        for manifest in discover_module_manifests(vendor_root):
            definition = load_module_definition(manifest)
            vendored[definition.name] = definition
    # Vendored snapshots match deployment precedence when a local migration
    # example and a packaged production module share a name.
    available = {**local, **vendored}
    return enabled, local, vendored, available


def _add_vendored_source_roots() -> None:
    """Expose conventional vendored ``modules`` roots for shallow resolution."""
    vendor_root = REPO_ROOT / "vendor" / "modules"
    if not vendor_root.exists():
        return
    for module_repo in sorted(vendor_root.iterdir()):
        source_root = module_repo / "modules"
        if source_root.is_dir():
            source_root_text = str(source_root)
            if source_root_text not in sys.path:
                sys.path.insert(0, source_root_text)


def _module_availability_checks() -> tuple[list[SelfTestCheck], dict[str, Any]]:
    """Check discovery and return reusable module context for later probes."""
    try:
        enabled, local, vendored, available = _load_module_definitions()
    except Exception as exc:  # noqa: BLE001 - self-test reports exact failure
        return (
            [
                _check(
                    "module_discovery",
                    FATAL,
                    False,
                    f"Module discovery failed: {type(exc).__name__}: {exc}",
                )
            ],
            {"enabled": set(), "available": {}},
        )

    missing = sorted(enabled - set(available))
    checks = [
        _check(
            "module_discovery",
            FATAL,
            True,
            "Local and vendored module manifests were discovered",
            enabled=sorted(enabled),
            local=sorted(local),
            vendored=sorted(vendored),
        ),
        _check(
            "enabled_modules_available",
            FATAL,
            not missing,
            "Every enabled module is locally bundled or installed"
            if not missing
            else "Enabled module(s) are missing: " + ", ".join(missing),
            missing=missing,
        ),
    ]
    return checks, {"enabled": enabled, "available": available}


def _resolve_handler_module(handler_path: str) -> None:
    """Verify handler syntax and module availability without importing it."""
    module_name, sep, attr = handler_path.partition(":")
    if not sep or not module_name or not attr:
        raise ValueError("handler must be in module.path:function form")
    try:
        resolved = importlib.util.find_spec(module_name)
    except (ModuleNotFoundError, ValueError):
        resolved = None
    if resolved is None and not _vendored_module_path(module_name):
        raise ModuleNotFoundError(module_name)


def _vendored_package_dirs() -> dict[str, Path]:
    """Return setuptools package-name mappings from vendored pyprojects."""
    mappings: dict[str, Path] = {}
    vendor_root = REPO_ROOT / "vendor" / "modules"
    if not vendor_root.exists():
        return mappings

    for pyproject_path in sorted(vendor_root.glob("*/pyproject.toml")):
        try:
            config = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            package_dirs = config["tool"]["setuptools"]["package-dir"]
        except (KeyError, OSError, tomllib.TOMLDecodeError, TypeError):
            continue
        if not isinstance(package_dirs, dict):
            continue
        for package_name, relative_path in package_dirs.items():
            if not isinstance(package_name, str) or not isinstance(relative_path, str):
                continue
            package_root = pyproject_path.parent / relative_path
            if package_root.is_dir():
                mappings[package_name] = package_root
    return mappings


def _vendored_module_path(module_name: str) -> Path | None:
    """Resolve a dotted module beneath declared vendored package directories."""
    package_name, *children = module_name.split(".")
    package_root = _vendored_package_dirs().get(package_name)
    if package_root is None:
        return None
    candidate = package_root.joinpath(*children)
    module_file = candidate.with_suffix(".py")
    if module_file.is_file():
        return module_file
    init_file = candidate / "__init__.py"
    return init_file if init_file.is_file() else None


def _module_handler_checks(
    enabled: set[str],
    available: dict[str, Any],
    *,
    deep_import_handlers: bool = False,
) -> list[SelfTestCheck]:
    """Check every enabled job handler at shallow or deep import depth."""
    errors: list[str] = []
    checked: list[str] = []
    for module_name in sorted(enabled):
        definition = available.get(module_name)
        if definition is None:
            continue
        for job in (*definition.cron_jobs, *definition.worker_jobs):
            if not getattr(job, "handler", None):
                continue
            label = f"{module_name}/{job.name}"
            checked.append(label)
            try:
                if deep_import_handlers:
                    _deep_import_handler(job.handler)
                else:
                    _resolve_handler_module(job.handler)
            except Exception as exc:  # noqa: BLE001 - self-test reports exact failure
                errors.append(f"{label}: {type(exc).__name__}: {exc}")

    return [
        _check(
            "module_handlers_importable",
            FATAL,
            not errors,
            "Enabled module job handler modules are resolvable"
            if not errors
            else "One or more enabled module job handler modules failed to resolve",
            checked=checked,
            errors=errors,
        )
    ]


def _module_blueprint_checks(
    enabled: set[str],
    available: dict[str, Any],
) -> list[SelfTestCheck]:
    """Verify that every enabled module blueprint entry point is resolvable."""
    errors: list[str] = []
    checked: list[str] = []
    for module_name in sorted(enabled):
        definition = available.get(module_name)
        if definition is None or not definition.blueprint_entry_point:
            continue
        checked.append(f"{module_name}:{definition.blueprint_entry_point}")
        try:
            _resolve_handler_module(definition.blueprint_entry_point)
        except Exception as exc:  # noqa: BLE001 - self-test reports exact failure
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    return [
        _check(
            "module_blueprints_importable",
            FATAL,
            not errors,
            "Enabled module Blueprint modules are resolvable"
            if not errors
            else "One or more enabled module Blueprint modules failed to resolve",
            checked=checked,
            errors=errors,
        )
    ]


def _deep_import_handler(handler_path: str) -> None:
    """Import a handler, loading its vendored package alias when necessary."""
    module_name, sep, attr = handler_path.partition(":")
    if not sep or not module_name or not attr:
        raise ValueError("handler must be in module.path:function form")
    package_name = module_name.split(".", 1)[0]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        _load_vendored_package_alias(package_name)
        module = importlib.import_module(module_name)
    handler = getattr(module, attr)
    if not callable(handler):
        raise ValueError(f"handler is not callable: {handler_path}")


def _load_vendored_package_alias(package_name: str) -> ModuleType:
    """Load one vendored package under its production import name."""
    package_root = _vendored_package_dirs().get(package_name)
    if package_root is None:
        raise ModuleNotFoundError(package_name)
    init_file = package_root / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        package_name,
        init_file,
        submodule_search_locations=[str(package_root)],
    )
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(package_name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    # Remove half-initialized modules on failure so later checks/imports do not
    # observe a poisoned sys.modules entry.
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(package_name, None)
        raise
    return module


def _vendored_resource_exists(module_name: str, resource_path: str) -> bool:
    """Return whether a declared resource exists in supported source layouts."""
    candidates = (
        REPO_ROOT / "vendor" / "modules" / module_name / "modules" / module_name / resource_path,
        REPO_ROOT / "modules" / module_name / resource_path,
    )
    return any(path.is_file() for path in candidates)


def _package_resource_exists(resource_spec: str, module_name: str) -> bool:
    """Resolve a package resource with a vendored-tree development fallback."""
    package, sep, resource_path = resource_spec.partition(":")
    if not sep:
        return False
    try:
        return (resources.files(package) / resource_path).is_file()
    except Exception:
        return _vendored_resource_exists(module_name, resource_path)


def _resource_exists(resource_spec: str | None, module_name: str) -> bool:
    """Check URL, absolute, package, and vendored resource-spec forms."""
    if not resource_spec:
        return True
    if resource_spec.startswith(("http://", "https://")):
        return True
    if resource_spec.startswith("/"):
        return Path(resource_spec).is_file()
    return _package_resource_exists(resource_spec, module_name)


def _module_resource_checks(enabled: set[str], available: dict[str, Any]) -> list[SelfTestCheck]:
    """Verify every enabled frontend's declared script, styles, and docs."""
    missing: list[str] = []
    checked: list[str] = []
    for module_name in sorted(enabled):
        definition = available.get(module_name)
        if definition is None or not definition.frontend:
            continue
        frontend = definition.frontend
        resources_to_check: Iterable[tuple[str, str | None]] = (
            ("script", frontend.script),
            ("docs", frontend.docs),
            *((f"style[{index}]", style) for index, style in enumerate(frontend.styles)),
        )
        for label, resource_spec in resources_to_check:
            if not resource_spec:
                continue
            checked.append(f"{module_name}:{label}={resource_spec}")
            if not _resource_exists(resource_spec, module_name):
                missing.append(f"{module_name}:{label}={resource_spec}")

    return [
        _check(
            "module_frontend_resources",
            FATAL,
            not missing,
            "Enabled module frontend assets/docs exist"
            if not missing
            else "One or more enabled module frontend assets/docs are missing",
            checked=checked,
            missing=missing,
        )
    ]


def _redis_check() -> SelfTestCheck:
    """Perform the optional live Redis PING probe."""
    try:
        from redis_state import r

        r.ping()
    except Exception as exc:  # noqa: BLE001 - self-test reports exact failure
        return _check(
            "redis",
            FATAL,
            False,
            f"Redis ping failed: {type(exc).__name__}: {exc}",
        )
    return _check("redis", FATAL, True, "Redis answered PING")


def _toolsdb_check() -> SelfTestCheck:
    """Perform the optional live ToolsDB SELECT probe."""
    try:
        from toolsdb import get_conn

        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - self-test reports exact failure
        return _check(
            "toolsdb",
            FATAL,
            False,
            f"ToolsDB query failed: {type(exc).__name__}: {exc}",
        )
    return _check("toolsdb", FATAL, True, "ToolsDB answered SELECT 1")


def run_selftest(
    *,
    include_services: bool = False,
    deep_import_handlers: bool = False,
) -> SelfTestResult:
    """Run deterministic repository probes and optional service connectivity."""
    checks: list[SelfTestCheck] = [_import_dependencies()]
    module_checks, module_context = _module_availability_checks()
    checks.extend(module_checks)

    enabled = module_context["enabled"]
    available = module_context["available"]
    if available:
        checks.extend(
            _module_handler_checks(
                enabled,
                available,
                deep_import_handlers=deep_import_handlers,
            )
        )
        checks.extend(_module_blueprint_checks(enabled, available))
        checks.extend(_module_resource_checks(enabled, available))

    # Service checks are opt-in so image builds and developer linting do not
    # require credentials or a running local stack.
    if include_services:
        checks.extend([_redis_check(), _toolsdb_check()])

    return SelfTestResult(tuple(checks))


def _print_text(result: SelfTestResult) -> None:
    """Render a compact human-readable report to stdout."""
    print(f"Buckbot self-test: {result.status}")
    for check in result.checks:
        marker = "ok" if check.ok else check.severity
        print(f"[{marker}] {check.name}: {check.message}")
        if check.detail and not check.ok:
            for key, value in check.detail.items():
                if value:
                    print(f"  {key}: {value}")


def main(argv: list[str] | None = None) -> int:
    """Parse CLI options, run checks, print the report, and return its exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--services",
        action="store_true",
        help="also check Redis and ToolsDB connectivity",
    )
    parser.add_argument(
        "--deep-import-handlers",
        action="store_true",
        help="import handler modules and validate callable attributes",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero for warning/degraded results, not only fatal failures",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)

    result = run_selftest(
        include_services=args.services,
        deep_import_handlers=args.deep_import_handlers,
    )
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        _print_text(result)
    return result.exit_code(strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
