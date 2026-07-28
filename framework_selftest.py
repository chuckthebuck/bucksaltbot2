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
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent
FATAL = "fatal"
DEGRADED = "degraded"
WARNING = "warning"
OK = "ok"


@dataclass(frozen=True)
class SelfTestCheck:
    name: str
    severity: str
    ok: bool
    message: str
    detail: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
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
    checks: tuple[SelfTestCheck, ...]

    @property
    def status(self) -> str:
        if any(not check.ok and check.severity == FATAL for check in self.checks):
            return FATAL
        if any(not check.ok and check.severity == DEGRADED for check in self.checks):
            return DEGRADED
        if any(not check.ok and check.severity == WARNING for check in self.checks):
            return WARNING
        return OK

    def exit_code(self, *, strict: bool = False) -> int:
        if self.status == FATAL:
            return 1
        if strict and self.status in {DEGRADED, WARNING}:
            return 1
        return 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks": [check.as_dict() for check in self.checks],
        }


def _check(name: str, severity: str, ok: bool, message: str, **detail: Any) -> SelfTestCheck:
    return SelfTestCheck(
        name=name,
        severity=severity,
        ok=ok,
        message=message,
        detail={key: value for key, value in detail.items() if value is not None} or None,
    )


def _import_dependencies() -> SelfTestCheck:
    required = ("flask", "mwoauth", "requests", "redis", "pymysql", "celery")
    missing: list[str] = []
    for module_name in required:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError:
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
    available = {**local, **vendored}
    return enabled, local, vendored, available


def _add_vendored_source_roots() -> None:
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
    module_name, sep, attr = handler_path.partition(":")
    if not sep or not module_name or not attr:
        raise ValueError("handler must be in module.path:function form")
    if importlib.util.find_spec(module_name) is None:
        raise ModuleNotFoundError(module_name)


def _module_handler_checks(
    enabled: set[str],
    available: dict[str, Any],
    *,
    deep_import_handlers: bool = False,
) -> list[SelfTestCheck]:
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


def _deep_import_handler(handler_path: str) -> None:
    module_name, sep, attr = handler_path.partition(":")
    if not sep or not module_name or not attr:
        raise ValueError("handler must be in module.path:function form")
    module = importlib.import_module(module_name)
    handler = getattr(module, attr)
    if not callable(handler):
        raise ValueError(f"handler is not callable: {handler_path}")


def _vendored_resource_exists(module_name: str, resource_path: str) -> bool:
    candidates = (
        REPO_ROOT / "vendor" / "modules" / module_name / "modules" / module_name / resource_path,
        REPO_ROOT / "modules" / module_name / resource_path,
    )
    return any(path.is_file() for path in candidates)


def _package_resource_exists(resource_spec: str, module_name: str) -> bool:
    package, sep, resource_path = resource_spec.partition(":")
    if not sep:
        return False
    try:
        return (resources.files(package) / resource_path).is_file()
    except Exception:
        return _vendored_resource_exists(module_name, resource_path)


def _resource_exists(resource_spec: str | None, module_name: str) -> bool:
    if not resource_spec:
        return True
    if resource_spec.startswith(("http://", "https://")):
        return True
    if resource_spec.startswith("/"):
        return Path(resource_spec).is_file()
    return _package_resource_exists(resource_spec, module_name)


def _module_resource_checks(enabled: set[str], available: dict[str, Any]) -> list[SelfTestCheck]:
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
        checks.extend(_module_resource_checks(enabled, available))

    if include_services:
        checks.extend([_redis_check(), _toolsdb_check()])

    return SelfTestResult(tuple(checks))


def _print_text(result: SelfTestResult) -> None:
    print(f"Buckbot self-test: {result.status}")
    for check in result.checks:
        marker = "ok" if check.ok else check.severity
        print(f"[{marker}] {check.name}: {check.message}")
        if check.detail and not check.ok:
            for key, value in check.detail.items():
                if value:
                    print(f"  {key}: {value}")


def main(argv: list[str] | None = None) -> int:
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
