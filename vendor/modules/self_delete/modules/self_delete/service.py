"""Cron handler for parallel, revalidated, SQL-audited G7 self-deletion."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .audit import SQLAuditStore
from .config import Settings
from .models import Candidate, Inspection
from .queue import enqueue_self_delete_batch
from .wiki import CommonsGateway


def _message(exc: BaseException) -> str:
    """Return a non-empty exception description for durable storage."""
    return str(exc).strip() or exc.__class__.__name__


def run_self_delete(
    ctx: Any,
    payload: dict[str, Any] | None = None,
    *,
    audit_store: Any | None = None,
    gateway_factory: Callable[[], CommonsGateway] | None = None,
    queue_submitter: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one bounded scan and return a JSON-safe aggregate report.

    The injectable audit store and gateway factory keep policy tests hermetic;
    the framework invokes only the normal ``(ctx, payload)`` signature.
    """
    # Runtime configuration is authoritative for live permission. A caller can
    # force a single run into dry-run mode, but an ad-hoc payload can never turn
    # configured dry-run protection off.
    config_values = (
        ctx.config.as_dict() if hasattr(ctx.config, "as_dict") else dict(ctx.config)
    )
    settings = Settings.from_mapping(config_values)
    if isinstance(payload, dict) and payload.get("dry_run") is True:
        settings = replace(settings, dry_run=True)
    audit = audit_store or SQLAuditStore()
    run_id = audit.create_run(
        framework_run_id=getattr(ctx, "run_id", None), settings=settings
    )
    counts = {"discovered": 0, "eligible": 0, "deleted": 0, "skipped": 0, "failed": 0}

    def log(message: str) -> None:
        """Prefix framework log output with the SQL audit run identifier."""
        ctx.logger.log(f"self-delete run={run_id} {message}")

    if not settings.enabled:
        audit.event(run_id, None, "info", "run_disabled", "Module is disabled", {})
        audit.finish_run(run_id, status="disabled", **counts)
        return {"status": "disabled", "run_id": run_id, **counts}

    if not settings.dry_run and os.environ.get("CHUCKBOT_LOCAL_SAFE_MODE"):
        detail = "Local safe mode blocks live self-delete actions"
        audit.event(run_id, None, "error", "safe_mode_blocked", detail, {})
        audit.finish_run(run_id, status="failed", error=detail, **counts)
        raise RuntimeError(detail)

    if gateway_factory is None:
        gateway_factory = lambda: CommonsGateway(ctx.site("commons", "commons"))
    queue_submitter = queue_submitter or enqueue_self_delete_batch

    thread_state = threading.local()

    def gateway() -> CommonsGateway:
        """Return one independently authenticated gateway per worker thread."""
        existing = getattr(thread_state, "gateway", None)
        if existing is None:
            existing = gateway_factory()
            thread_state.gateway = existing
        return existing

    candidate_ids: dict[str, int] = {}
    inspection_results: dict[str, Inspection] = {}

    try:
        ctx.check_cancelled()
        audit.event(
            run_id,
            None,
            "info",
            "run_started",
            "Starting category discovery",
            settings.as_dict(),
        )
        candidates = gateway_factory().discover(
            settings.category_title, settings.max_candidates
        )
        counts["discovered"] = len(candidates)
        log(f"discovered={len(candidates)} category={settings.category_title!r}")
        for candidate in candidates:
            candidate_ids[candidate.title] = audit.add_candidate(run_id, candidate)

        def inspect_one(candidate: Candidate) -> Inspection:
            """Inspect one candidate and persist its complete initial decision."""
            ctx.check_cancelled()
            candidate_id = candidate_ids[candidate.title]
            audit.event(
                run_id,
                candidate_id,
                "info",
                "inspection_started",
                "Initial policy inspection started",
                {},
            )
            result = gateway().inspect(
                candidate,
                now=datetime.now(timezone.utc),
                max_age_seconds=settings.max_age_seconds,
            )
            audit.inspection(run_id, candidate_id, result, phase="initial")
            return result

        with ThreadPoolExecutor(
            max_workers=settings.workers, thread_name_prefix="self-delete-check"
        ) as pool:
            future_candidates = {
                pool.submit(inspect_one, candidate): candidate
                for candidate in candidates
            }
            for future in as_completed(future_candidates):
                candidate = future_candidates[future]
                candidate_id = candidate_ids[candidate.title]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - isolate per-file failures
                    detail = _message(exc)
                    counts["failed"] += 1
                    audit.set_candidate_status(
                        run_id, candidate_id, "failed", "inspection_error", detail
                    )
                    log(f"inspection failed title={candidate.title!r} error={detail}")
                    continue
                inspection_results[candidate.title] = result
                if result.eligible:
                    counts["eligible"] += 1
                else:
                    counts["skipped"] += 1

        eligible = [
            candidate
            for candidate in candidates
            if inspection_results.get(candidate.title)
            and inspection_results[candidate.title].eligible
        ]

        if eligible:
            ctx.check_cancelled()
            queue_result = queue_submitter(
                settings=settings,
                run_id=run_id,
                candidates=eligible,
                candidate_ids=candidate_ids,
                inspections=inspection_results,
            )
            audit.mark_run_queued(
                run_id,
                discovered=counts["discovered"],
                eligible=counts["eligible"],
                skipped=counts["skipped"],
                failed=counts["failed"],
                queue_result=queue_result,
            )
            status = "queued"
            log(f"queued self-delete jobs={queue_result.get('job_ids', [])}")
        else:
            queue_result = {
                "job_ids": [],
                "batch_id": None,
                "chunks": 0,
                "total_items": 0,
            }
            status = "failed" if counts["failed"] else "completed"
            audit.event(run_id, None, "info", "run_finished", "Run finished", counts)
            audit.finish_run(run_id, status=status, **counts)
            log(f"finished status={status} counts={counts}")

        return {
            "status": status,
            "run_id": run_id,
            "dry_run": settings.dry_run,
            "category_title": settings.category_title,
            "queue": queue_result,
            **counts,
        }
    except Exception as exc:
        detail = _message(exc)
        audit.event(run_id, None, "error", "run_failed", detail, counts)
        audit.finish_run(run_id, status="failed", error=detail, **counts)
        log(f"failed error={detail}")
        raise
