"""Execute one manifest-declared module handler in an isolated process.

The runner validates current registry state, creates a narrow context object,
activates module-specific OAuth only when declared, and converts handler outcomes
into durable run state.  The outer controller provides a second hard timeout and
process cancellation boundary for handlers that cannot cooperate.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import inspect
import importlib
import json
import os
from pathlib import Path
import signal
import threading
from typing import Any

from logger import Logger
from pywikibot_env import ensure_pywikibot_env
from router.module_registry import (
    ModuleJobConcurrencyError,
    bootstrap_installed_module_definitions,
    bootstrap_module_definitions,
    create_module_job_run,
    get_module_config,
    get_module_definition,
    get_module_job_run,
    load_enabled_module_names,
    update_module_job_run,
)


class ModuleRunCancelled(RuntimeError):
    """Raised when a module run was canceled through the framework."""


class ModuleRunTimedOut(TimeoutError):
    """Raised when an isolated module handler exceeds its manifest timeout."""


class _ConfigView(Mapping[str, Any]):
    """Read-only mapping facade over the effective module configuration."""

    def __init__(self, values: dict[str, Any]):
        """Copy values so handler mutations cannot alter the source dictionary."""
        self._values = dict(values)

    def __getitem__(self, key: str) -> Any:
        """Return one configuration value by key."""
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate configuration keys."""
        return iter(self._values)

    def __len__(self) -> int:
        """Return the number of effective configuration keys."""
        return len(self._values)

    def as_dict(self) -> dict[str, Any]:
        """Return a mutable copy for legacy handlers that require a dictionary."""
        return dict(self._values)


class _FallbackLogger:
    """Stdout logger used when a file logger cannot be opened in the container."""

    def __init__(self, name: str):
        """Remember the component prefix included in every message."""
        self.name = name

    def log(self, message: str) -> None:
        """Write one prefixed message to stdout."""
        print(f"[{self.name}] {message}")


@dataclass(frozen=True)
class ModuleRunContext:
    """Narrow framework capability object passed to module handlers."""

    module_name: str
    job_name: str
    run_id: int
    config: _ConfigView
    logger: Any

    def check_cancelled(self) -> None:
        """Raise when durable state contains a cooperative cancel request."""
        run = get_module_job_run(self.run_id)
        if run and run.get("status") in {"cancel_requested", "canceled"}:
            raise ModuleRunCancelled(f"Run {self.run_id} was canceled")

    def site(self, code: str = "commons", family: str = "commons"):
        """Return an authenticated Pywikibot Site for trusted module code."""
        from pywikibot_env import ensure_pywikibot_env

        ensure_pywikibot_env(strict=True)
        import pywikibot

        site = pywikibot.Site(code, family)
        site.login()
        return site

    def execute_actions(
        self,
        actions,
        *,
        dry_run: bool = True,
        allowed_types=(),
    ):
        """Run a declarative action plan through the framework action catalog.

        Child scripts provide data only; the reviewed framework catalogue owns
        method dispatch, wiki construction, batching, and progress persistence.
        """
        from router.wiki_actions import execute_action_plan

        def record_batch(batch_number: int, processed: int, total: int) -> None:
            """Persist best-effort action-batch progress in this module's Redis key."""
            try:
                from redis_state import r

                r.hset(
                    f"module:{self.module_name}:run:{self.run_id}:action-batch",
                    mapping={
                        "batch": batch_number,
                        "processed": processed,
                        "total": total,
                    },
                )
                r.expire(f"module:{self.module_name}:run:{self.run_id}:action-batch", 86400)
            except Exception:
                # Progress reporting must never turn a completed wiki action
                # into a failed module job when Redis is unavailable.
                return

        return execute_action_plan(
            actions,
            site_factory=self.site,
            dry_run=dry_run,
            allowed_types=allowed_types,
            batch_callback=None if dry_run else record_batch,
        )


def _import_handler(handler_path: str):
    """Import and return a callable ``module.path:function`` handler."""
    module_path, sep, attr = str(handler_path or "").partition(":")
    if not sep or not module_path or not attr:
        raise ValueError("handler must be in module.path:function form")

    module = importlib.import_module(module_path)
    handler = getattr(module, attr)
    if not callable(handler):
        raise ValueError(f"handler is not callable: {handler_path}")
    return handler


def _build_logger(name: str):
    """Open a file logger when possible, otherwise retain stdout visibility."""
    try:
        return Logger(name)
    except Exception:
        return _FallbackLogger(name)


def _activate_module_oauth(definition) -> None:
    """Map a module's isolated credential variables into Pywikibot's names."""
    if definition.oauth_consumer_mode != "module":
        return

    credential_env = {
        "CONSUMER_TOKEN": definition.oauth_consumer_key_env,
        "CONSUMER_SECRET": definition.oauth_consumer_secret_env,
        "ACCESS_TOKEN": definition.oauth_access_token_env,
        "ACCESS_SECRET": definition.oauth_access_secret_env,
    }
    missing = [
        source_name
        for source_name in credential_env.values()
        if not source_name or not os.environ.get(source_name)
    ]
    if missing:
        raise RuntimeError(
            "Missing module OAuth credential environment variables: "
            + ", ".join(str(name) for name in missing)
        )

    # Pywikibot's user-config reads the generic target names.  Copy values only
    # inside this module-specific subprocess so credentials never leak to peers.
    for target_name, source_name in credential_env.items():
        os.environ[target_name] = os.environ[str(source_name)]


def _handler_call_args(handler, ctx: ModuleRunContext, payload: dict[str, Any]) -> tuple:
    """Return the richest supported framework handler call signature."""
    signature = inspect.signature(handler)
    try:
        signature.bind(ctx, payload)
    except TypeError:
        pass
    else:
        return (ctx, payload)

    positional_parameters = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }
    ]
    one_arg_value = (
        payload
        if len(positional_parameters) == 1
        and positional_parameters[0].name.lower() in {"payload", "data", "params"}
        else ctx
    )
    try:
        signature.bind(one_arg_value)
    except TypeError:
        pass
    else:
        return (one_arg_value,)

    try:
        signature.bind()
    except TypeError as exc:
        raise ValueError(
            "module handlers must accept (), (ctx), (payload), or (ctx, payload)"
        ) from exc
    return ()


def _invoke_handler(handler, ctx: ModuleRunContext, payload: dict[str, Any]) -> Any:
    """Invoke a handler using its richest supported compatibility signature."""
    return handler(*_handler_call_args(handler, ctx, payload))


@contextmanager
def _handler_timeout(timeout_seconds: int):
    """Enforce handler timeout in standalone scheduled runner processes."""
    supported = (
        os.name == "posix"
        and threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
    )
    if not supported:
        yield
        return

    def _raise_timeout(_signum, _frame):
        """Translate SIGALRM into the runner's typed timeout outcome."""
        raise ModuleRunTimedOut(
            f"Module job timed out after {int(timeout_seconds)} seconds"
        )

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _json_safe_result(result: Any) -> dict[str, Any]:
    """Normalize arbitrary handler results into a JSON-storable dictionary."""
    payload = result if isinstance(result, dict) else {"result": result}
    return json.loads(json.dumps(payload, default=str))


def _bootstrap_local_registry() -> None:
    """Populate the child process registry from local and installed definitions."""
    enabled_module_names = load_enabled_module_names()
    modules_root = Path(__file__).resolve().parent / "modules"
    if modules_root.exists():
        bootstrap_module_definitions(modules_root, enabled_names=enabled_module_names)
    bootstrap_installed_module_definitions(enabled_names=enabled_module_names)


def run_module_job(
    module_name: str,
    job_name: str,
    *,
    run_id: int | None = None,
    trigger_type: str = "schedule",
    triggered_by: str | None = None,
) -> int:
    """Run one enabled module job and persist a terminal process outcome."""
    os.environ.setdefault("NOTDEV", "1")
    _bootstrap_local_registry()

    record = get_module_definition(module_name)
    if record is None:
        raise ValueError(f"Unknown module: {module_name}")
    if not record.enabled:
        raise ValueError(f"Module is disabled: {module_name}")

    job = next(
        (
            j
            for j in (*record.definition.cron_jobs, *record.definition.worker_jobs)
            if j.name == job_name
        ),
        None,
    )
    if job is None:
        raise ValueError(f"Unknown module job: {module_name}/{job_name}")
    if not job.enabled:
        raise ValueError(f"Module job is disabled: {module_name}/{job_name}")
    if not job.handler:
        raise ValueError(f"Module job has no handler: {module_name}/{job_name}")

    if run_id is None:
        try:
            run_id = create_module_job_run(
                module_name,
                job_name,
                trigger_type=trigger_type,
                triggered_by=triggered_by,
                concurrency_policy=job.concurrency_policy,
            )
        except ModuleJobConcurrencyError:
            return 0
    else:
        existing_run = get_module_job_run(run_id) or {}
        if existing_run.get("status") in {"cancel_requested", "canceled"}:
            update_module_job_run(
                run_id,
                status="canceled",
                error=f"Run {run_id} was canceled",
                exit_code=130,
            )
            return 130

    logger = _build_logger(f"module.{module_name}.{job_name}")
    update_module_job_run(run_id, status="running")

    try:
        _activate_module_oauth(record.definition)
        ensure_pywikibot_env(strict=True)
        handler = _import_handler(job.handler)
        run = get_module_job_run(run_id) or {}
        payload = run.get("payload") or {}
        config_values = get_module_config(module_name)
        # Specialized trusted workflows may persist per-run overrides in the run
        # payload.  The generic HTTP run endpoint rejects this key before enqueue.
        config_overrides = payload.get("config_overrides")
        if isinstance(config_overrides, dict):
            config_values.update(config_overrides)
        # Safe mode only narrows capability, even if stored runtime configuration
        # or a trusted run override requested live publication.
        if os.getenv("CHUCKBOT_LOCAL_SAFE_MODE"):
            config_values["dry_run"] = True
            config_values["publish_dry_run_report"] = False
        ctx = ModuleRunContext(
            module_name=module_name,
            job_name=job_name,
            run_id=run_id,
            config=_ConfigView(config_values),
            logger=logger,
        )
        with _handler_timeout(job.timeout_seconds):
            result = _invoke_handler(handler, ctx, payload)
        update_module_job_run(
            run_id,
            status="completed",
            exit_code=0,
            result=_json_safe_result(result),
        )
        return 0
    except ModuleRunTimedOut as exc:
        logger.log(str(exc))
        update_module_job_run(run_id, status="failed", error=str(exc), exit_code=124)
        return 124
    except ModuleRunCancelled as exc:
        logger.log(str(exc))
        update_module_job_run(run_id, status="canceled", error=str(exc), exit_code=130)
        return 130
    except Exception as exc:
        logger.log(f"Module job failed: {exc}")
        update_module_job_run(run_id, status="failed", error=str(exc), exit_code=1)
        raise


def main(argv: list[str] | None = None) -> int:
    """Parse the isolated runner CLI and return the module job's exit code."""
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
