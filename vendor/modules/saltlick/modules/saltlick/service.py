"""Saltlick framework handler and execution engine."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import difflib
import re
import time
from typing import Any

from .codegen import render_jobs_py
from .sources import resolve_pages
from .spec import WorkflowSpec, recipe_with_invocation
from .transforms import apply_transforms


MAX_DIFF_CHARS_PER_PAGE = 20_000
MAX_DIFF_CHARS_PER_RUN = 250_000


def _log(ctx: Any | None, message: str) -> None:
    logger = getattr(ctx, "logger", None)
    if logger is not None and hasattr(logger, "log"):
        logger.log(message)


def _check_cancelled(ctx: Any | None) -> None:
    if ctx is not None and hasattr(ctx, "check_cancelled"):
        ctx.check_cancelled()


def _page_title(page: Any) -> str:
    title = page.title()
    return str(title)


def _page_namespace(page: Any) -> int:
    namespace = page.namespace()
    try:
        return int(namespace)
    except (TypeError, ValueError):
        return int(getattr(namespace, "id", 0))


def _render_summary(summary: str, *, title: str) -> str:
    page_name = title.split(":", 1)[-1]
    return (
        summary.replace("{{title}}", title)
        .replace("{{pagename}}", page_name)
        .strip()
    )


def _make_diff(title: str, before: str, after: str, remaining: int) -> str:
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
    config = getattr(ctx, "config", None)
    value = config.get(key, default) if hasattr(config, "get") else default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def run_saltlick(ctx: Any | None = None, payload: dict[str, Any] | None = None):
    """Run Saltlick through Chuckbot's isolated module runner."""
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
