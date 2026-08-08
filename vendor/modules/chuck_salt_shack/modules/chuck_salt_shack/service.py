"""Chuck the Salt Shack handler and child Saltlick execution engine."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import difflib
import hashlib
import json
import re
import time
from typing import Any

from .codegen import render_jobs_py
from .contracts import (
    public_contract,
    validate_actions,
    validate_arguments,
    validate_inputs,
    validate_outputs,
)
from .registry import get_saltlick, invoke_saltlick
from .sources import resolve_pages
from .spec import WorkflowSpec, recipe_with_invocation
from .transforms import apply_transforms


MAX_DIFF_CHARS_PER_PAGE = 20_000
MAX_DIFF_CHARS_PER_RUN = 250_000


def _log(ctx: Any | None, message: str) -> None:
    """Write through the framework logger when a run context provides one."""
    logger = getattr(ctx, "logger", None)
    if logger is not None and hasattr(logger, "log"):
        logger.log(message)


def _check_cancelled(ctx: Any | None) -> None:
    """Honor framework cancellation between bounded units of work."""
    if ctx is not None and hasattr(ctx, "check_cancelled"):
        ctx.check_cancelled()


def _page_title(page: Any) -> str:
    """Return a Pywikibot page title as plain text."""
    title = page.title()
    return str(title)


def _page_namespace(page: Any) -> int:
    """Normalize Pywikibot namespace objects and integers."""
    namespace = page.namespace()
    try:
        return int(namespace)
    except (TypeError, ValueError):
        return int(getattr(namespace, "id", 0))


def _render_summary(summary: str, *, title: str) -> str:
    """Expand the supported edit-summary title tokens."""
    page_name = title.split(":", 1)[-1]
    return (
        summary.replace("{{title}}", title)
        .replace("{{pagename}}", page_name)
        .strip()
    )


def _make_diff(title: str, before: str, after: str, remaining: int) -> str:
    """Create a per-page unified diff within the run's remaining budget."""
    if remaining <= 0:
        return ""
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{title} (before)",
            tofile=f"{title} (after)",
        )
    )
    limit = min(MAX_DIFF_CHARS_PER_PAGE, remaining)
    if len(diff) <= limit:
        return diff
    suffix = "\n... diff truncated by Saltlick ...\n"
    return diff[: max(0, limit - len(suffix))] + suffix


def _skip_reason(page: Any, title: str, text: str, spec: WorkflowSpec) -> str | None:
    """Return the first configured reason a legacy workflow should skip a page."""
    filters = spec.filters
    if filters.title_regex and not re.search(filters.title_regex, title):
        return "title_filter"
    if filters.contains and filters.contains not in text:
        return "missing_required_text"
    if filters.not_contains and filters.not_contains in text:
        return "contains_excluded_text"
    if filters.skip_redirects and page.isRedirectPage():
        return "redirect"
    return None


def execute_workflow(
    site: Any,
    spec: WorkflowSpec | dict[str, Any],
    *,
    dry_run: bool = True,
    ctx: Any | None = None,
    pages: Iterable[Any] | None = None,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    """Execute one validated workflow and return a bounded run report."""
    workflow = spec if isinstance(spec, WorkflowSpec) else WorkflowSpec.from_dict(spec)
    page_iter = pages if pages is not None else resolve_pages(site, workflow.source)
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items: list[dict[str, Any]] = []
    dry_run_edits: list[dict[str, Any]] = []
    changed = saved = skipped = errors = scanned = 0
    diff_chars = 0

    _log(
        ctx,
        f"Saltlick {'previewing' if dry_run else 'applying'} {workflow.name}",
    )
    for page in page_iter:
        _check_cancelled(ctx)
        if changed >= workflow.limits.max_edits:
            break
        scanned += 1
        title = _page_title(page)
        item: dict[str, Any] = {"title": title}
        try:
            exists = bool(page.exists())
            if not exists:
                if workflow.filters.skip_missing:
                    item.update(status="skipped", reason="missing")
                    skipped += 1
                    items.append(item)
                    continue
                old_text = ""
            else:
                old_text = str(page.text)
            if len(old_text.encode("utf-8")) > workflow.limits.max_page_bytes:
                item.update(status="skipped", reason="page_too_large")
                skipped += 1
                items.append(item)
                continue
            reason = _skip_reason(page, title, old_text, workflow)
            if reason:
                item.update(status="skipped", reason=reason)
                skipped += 1
                items.append(item)
                continue
            namespace = _page_namespace(page)
            new_text = apply_transforms(
                old_text,
                workflow.transforms,
                title=title,
                namespace=namespace,
            )
            if new_text == old_text:
                item.update(status="unchanged")
                items.append(item)
                continue
            if len(new_text.encode("utf-8")) > workflow.limits.max_page_bytes:
                raise ValueError("transformed page exceeds max_page_bytes")

            changed += 1
            diff = _make_diff(
                title,
                old_text,
                new_text,
                MAX_DIFF_CHARS_PER_RUN - diff_chars,
            )
            diff_chars += len(diff)
            summary = _render_summary(workflow.save.summary, title=title)
            status = "proposed"
            if not dry_run:
                if not summary:
                    raise ValueError("live edits require a non-empty edit summary")
                page.text = new_text
                page.save(
                    summary=summary,
                    minor=workflow.save.minor,
                    botflag=workflow.save.bot,
                    watch=workflow.save.watch,
                )
                saved += 1
                status = "saved"
                if workflow.save.throttle_seconds:
                    sleep(workflow.save.throttle_seconds)
            item.update(
                status=status,
                changed=True,
                summary=summary,
                diff=diff,
            )
            dry_run_edits.append(
                {
                    "title": title,
                    "summary": summary,
                    "status": status,
                    "diff": diff,
                }
            )
        except Exception as exc:  # one bad page should not erase a useful run report
            errors += 1
            item.update(status="error", error=str(exc))
            if workflow.limits.stop_on_error:
                items.append(item)
                break
        items.append(item)

    return {
        "ok": errors == 0,
        "workflow": workflow.name,
        "started_at": started_at,
        "dry_run": bool(dry_run),
        "site": {
            "code": workflow.wiki.code,
            "family": workflow.wiki.family,
        },
        "scanned_count": scanned,
        "changed_count": changed,
        "saved_count": saved,
        "skipped_count": skipped,
        "error_count": errors,
        "items": items,
        "dry_run_edits": dry_run_edits,
        "generated_jobs_py": render_jobs_py(workflow),
    }


def _config_bool(ctx: Any | None, key: str, default: bool = False) -> bool:
    """Read a boolean module setting from the framework run context."""
    config = getattr(ctx, "config", None)
    value = config.get(key, default) if hasattr(config, "get") else default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _run_legacy_workflow(
    ctx: Any | None = None,
    payload: dict[str, Any] | None = None,
):
    """Run the pre-Salt-Shack recipe format for compatibility."""
    data = payload or {}
    unknown = sorted(set(data) - {"recipe", "inputs", "arguments", "confirm_live"})
    if unknown:
        raise ValueError(f"unsupported run argument(s): {', '.join(unknown)}")
    workflow = WorkflowSpec.from_dict(
        recipe_with_invocation(
            data.get("recipe"),
            inputs=data.get("inputs"),
            arguments=data.get("arguments"),
        )
    )
    job_name = str(getattr(ctx, "job_name", "preview") or "preview")
    apply_job = job_name == "apply"
    if apply_job and data.get("confirm_live") is not True:
        raise ValueError("live Saltlick runs require confirm_live=true")
    forced_dry_run = _config_bool(ctx, "dry_run", False)
    dry_run = not apply_job or forced_dry_run
    site = data.get("_site")
    if site is None:
        if ctx is None or not hasattr(ctx, "site"):
            raise RuntimeError("Saltlick requires a framework context or injected site")
        site = ctx.site(workflow.wiki.code, workflow.wiki.family)
    return execute_workflow(site, workflow, dry_run=dry_run, ctx=ctx)


def _plan_token(
    *,
    saltlick_id: str,
    inputs: dict[str, Any],
    arguments: list[str],
    actions: list[dict[str, Any]],
) -> str:
    """Bind a previewed action plan to its exact normalized invocation."""
    payload = {
        "saltlick_id": saltlick_id,
        "inputs": inputs,
        "arguments": arguments,
        "actions": actions,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def execute_saltlick(
    ctx: Any | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate, dispatch, and report one immutable Saltlick."""
    allowed_payload = {
        "saltlick_id",
        "inputs",
        "arguments",
        "confirm_live",
        "preview_token",
    }
    unknown = sorted(set(payload) - allowed_payload)
    if unknown:
        raise ValueError(f"unsupported run argument(s): {', '.join(unknown)}")

    saltlick_id = str(payload.get("saltlick_id") or "").strip()
    definition = get_saltlick(saltlick_id)
    if definition is None:
        raise ValueError(f"unknown Saltlick: {saltlick_id}")
    inputs = validate_inputs(definition.contract, payload.get("inputs"))
    arguments = validate_arguments(payload.get("arguments"))

    job_name = str(getattr(ctx, "job_name", "preview") or "preview")
    apply_job = job_name == "apply"
    if apply_job and payload.get("confirm_live") is not True:
        raise ValueError("live Saltlick runs require confirm_live=true")
    forced_dry_run = _config_bool(ctx, "dry_run", False)
    dry_run = not apply_job or forced_dry_run

    raw_result = invoke_saltlick(
        definition,
        ctx=ctx,
        inputs=inputs,
        arguments=arguments,
    )
    if raw_result is None:
        raw_result = {}
    if not isinstance(raw_result, dict):
        raise ValueError("Saltlick run functions must return an object")
    unknown_result = sorted(set(raw_result) - {"outputs", "actions"})
    if unknown_result:
        raise ValueError(
            "Saltlick returned unsupported field(s): "
            + ", ".join(unknown_result)
        )
    outputs = validate_outputs(
        definition.contract,
        raw_result.get("outputs"),
    )
    actions = validate_actions(
        definition.contract,
        raw_result.get("actions"),
    )
    plan_token = _plan_token(
        saltlick_id=definition.id,
        inputs=inputs,
        arguments=arguments,
        actions=actions,
    )
    if apply_job and not forced_dry_run:
        supplied_token = str(payload.get("preview_token") or "")
        if not supplied_token:
            raise ValueError("live Saltlick runs require a preview_token")
        if supplied_token != plan_token:
            raise ValueError(
                "Saltlick action plan changed after preview; preview it again"
            )

    if ctx is None or not hasattr(ctx, "execute_actions"):
        if actions and not dry_run:
            raise RuntimeError(
                "live Saltlick actions require a framework run context"
            )
        action_result = {
            "ok": True,
            "dry_run": True,
            "planned_count": len(actions),
            "completed_count": 0,
            "error_count": 0,
            "items": [
                {
                    "index": index,
                    **action,
                    "status": "planned",
                }
                for index, action in enumerate(actions)
            ],
        }
    else:
        action_result = ctx.execute_actions(
            actions,
            dry_run=dry_run,
            allowed_types=definition.contract["actions"]["allowed"],
        )

    return {
        "ok": bool(action_result.get("ok", True)),
        "saltlick": {
            "id": definition.id,
            "display_name": definition.contract["display_name"],
            "source_digest": definition.source_digest,
        },
        "contract": public_contract(definition.contract),
        "inputs": inputs,
        "arguments": arguments,
        "outputs": outputs,
        "actions": actions,
        "action_result": action_result,
        "dry_run": bool(dry_run),
        "plan_token": plan_token,
    }


def run_saltlick(ctx: Any | None = None, payload: dict[str, Any] | None = None):
    """Run a Salt Shack child Saltlick through Chuckbot's isolated runner."""
    data = payload or {}
    if "recipe" in data:
        return _run_legacy_workflow(ctx, data)
    return execute_saltlick(ctx, data)
