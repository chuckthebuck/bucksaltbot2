"""Isolated module job runner for Chuck the Buckbot Framework."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import inspect
import importlib
import os
from pathlib import Path
from typing import Any

from logger import Logger
from router.module_registry import (
    bootstrap_installed_module_definitions,
    bootstrap_module_definitions,
    create_module_job_run,
    get_module_config,
    get_module_definition,
    get_module_job_run,
    list_module_job_runs,
    update_module_job_run,
)


class ModuleRunCancelled(RuntimeError):
    """Raised when a module run was canceled through the framework."""


class _ConfigView:
    def __init__(self, values: dict[str, Any]):
        self._values = dict(values)

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._values)


class _FallbackLogger:
    def __init__(self, name: str):
        self.name = name

    def log(self, message: str) -> None:
        print(f"[{self.name}] {message}")


@dataclass(frozen=True)
class ModuleRunContext:
    module_name: str
    job_name: str
    run_id: int
    config: _ConfigView
    logger: Any

    def check_cancelled(self) -> None:
        run = get_module_job_run(self.run_id)
        if run and run.get("status") == "cancel_requested":
            raise ModuleRunCancelled(f"Run {self.run_id} was canceled")

    def site(self, code: str = "commons", family: str = "commons"):
        """Return a full pywikibot Site for module code."""
        from pywikibot_env import ensure_pywikibot_env

        ensure_pywikibot_env(strict=True)
        import pywikibot

        site = pywikibot.Site(code, family)
        site.login()
        return site


def _import_handler(handler_path: str):
    module_path, sep, attr = str(handler_path or "").partition(":")
    if not sep or not module_path or not attr:
        raise ValueError("handler must be in module.path:function form")

    module = importlib.import_module(module_path)
    handler = getattr(module, attr)
    if not callable(handler):
        raise ValueError(f"handler is not callable: {handler_path}")
    return handler


def _build_logger(name: str):
    try:
        return Logger(name)
    except Exception:
        return _FallbackLogger(name)


def _bootstrap_local_registry() -> None:
    modules_root = Path(__file__).resolve().parent / "modules"
    if modules_root.exists():
        bootstrap_module_definitions(modules_root)
    bootstrap_installed_module_definitions()


def run_module_job(
    module_name: str,
    job_name: str,
    *,
    run_id: int | None = None,
    trigger_type: str = "schedule",
    triggered_by: str | None = None,
) -> int:
    """Run one module job and return a process exit code."""
    os.environ.setdefault("NOTDEV", "1")
    _bootstrap_local_registry()

    record = get_module_definition(module_name)
    if record is None:
        raise ValueError(f"Unknown module: {module_name}")
    if not record.enabled:
        raise ValueError(f"Module is disabled: {module_name}")

    job = next((j for j in record.definition.cron_jobs if j.name == job_name), None)
    if job is None:
        raise ValueError(f"Unknown module job: {module_name}/{job_name}")
    if not job.enabled:
        raise ValueError(f"Module job is disabled: {module_name}/{job_name}")
    if not job.handler:
        raise ValueError(f"Module job has no handler: {module_name}/{job_name}")

    if run_id is None:
        if job.concurrency_policy == "forbid":
            active_runs = list_module_job_runs(module_name, job_name=job_name, limit=20)
            if any(
                run.get("status") in {"queued", "launching", "running"}
                for run in active_runs
            ):
                return 0
        run_id = create_module_job_run(
            module_name,
            job_name,
            trigger_type=trigger_type,
            triggered_by=triggered_by,
        )

    logger = _build_logger(f"module.{module_name}.{job_name}")
    update_module_job_run(run_id, status="running")

    try:
        handler = _import_handler(job.handler)
        ctx = ModuleRunContext(
            module_name=module_name,
            job_name=job_name,
            run_id=run_id,
            config=_ConfigView(get_module_config(module_name)),
            logger=logger,
        )
        run = get_module_job_run(run_id) or {}
        payload = run.get("payload") or {}
        parameters = inspect.signature(handler).parameters
        if len(parameters) == 0:
            result = handler()
        else:
            result = handler(ctx, payload)
        update_module_job_run(
            run_id,
            status="completed",
            exit_code=0,
            result=result if isinstance(result, dict) else {"result": result},
        )
        return 0
    except ModuleRunCancelled as exc:
        logger.log(str(exc))
        update_module_job_run(run_id, status="canceled", error=str(exc), exit_code=130)
        return 130
    except Exception as exc:
        logger.log(f"Module job failed: {exc}")
        update_module_job_run(run_id, status="failed", error=str(exc), exit_code=1)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--trigger", default="schedule")
    parser.add_argument("--triggered-by")
    args = parser.parse_args(argv)

    return run_module_job(
        args.module,
        args.job,
        run_id=args.run_id,
        trigger_type=args.trigger,
        triggered_by=args.triggered_by,
    )


if __name__ == "__main__":
    raise SystemExit(main())
