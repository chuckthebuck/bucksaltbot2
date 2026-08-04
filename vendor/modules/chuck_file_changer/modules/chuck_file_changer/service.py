"""Resolve targets, plan wikitext changes, and optionally save to Commons.

The service is shared by direct module execution and durable queue workers.
Preview/apply mode is derived conservatively from both explicit apply intent
and dry-run configuration, and each page failure is isolated into its own plan
item. When a framework context supplies cancellation, it aborts the chunk.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from .config import COMMONS_SITE_CODE, COMMONS_SITE_FAMILY, http_headers, user_agent
from .models import FileChangePlanItem
from .planner import default_summary, operation_from_payload, plan_target
from .quarry import parse_targets_text, quarry_result_url, targets_from_records
from .source import has_vfc_source, resolve_vfc_source
from .wiki import WikiClient


def _config_value(ctx: Any | None, key: str, default: Any) -> Any:
    """Read one optional framework config value without requiring a context."""
    if ctx is None or not hasattr(ctx, "config"):
        return default
    cfg = ctx.config
    if hasattr(cfg, "get"):
        return cfg.get(key, default)
    return default


def _bool_value(value: Any, default: bool) -> bool:
    """Coerce common JSON/config booleans and fall back on ambiguous values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def targets_from_payload(payload: dict[str, Any]) -> tuple[list, str | None]:
    """Resolve targets using frozen rows, live source mode, Quarry, or text.

    Pre-parsed ``targets`` have highest precedence for durable chunks so a
    worker does not requery a mutable external source. Live Commons source modes
    precede Quarry, and pasted/manual text is the final fallback.
    """
    if isinstance(payload.get("targets"), list):
        return targets_from_records(payload["targets"]), payload.get("source_url")

    source_text = str(payload.get("targets_text") or payload.get("source_text") or "")
    quarry_input = str(payload.get("quarry") or payload.get("quarry_url") or "").strip()

    if has_vfc_source(payload):
        return resolve_vfc_source(payload)

    if quarry_input:
        url = quarry_result_url(quarry_input)
        if not url:
            raise ValueError("Quarry source must be a query URL, run URL, query ID, or run:ID")
        # ``quarry_result_url`` constrains the initial host/path; identified,
        # bounded-time HTTP is used consistently with Commons source requests.
        response = requests.get(url, headers=http_headers(), timeout=30)
        response.raise_for_status()
        return parse_targets_text(response.text), url

    return parse_targets_text(source_text), None


def edit_summary_for_target(base_summary: str, target) -> str:
    """Render the documented per-target edit-summary variables.

    ``%FULLPAGENAMEE%`` follows MediaWiki's common underscore form rather than
    performing general URL percent-encoding. If no explicit summary-hint token
    is present, a supplied hint is appended for provenance.
    """
    title = str(getattr(target, "title", "") or "")
    page_name = title.split(":", 1)[1] if ":" in title else title
    summary_hint = str(getattr(target, "summary_hint", "") or "")
    rendered = str(base_summary or "").replace("%FULLPAGENAME%", title)
    rendered = rendered.replace("%FULLPAGENAMEE%", title.replace(" ", "_"))
    rendered = rendered.replace("%PAGENAME%", page_name)
    rendered = rendered.replace("%SUMMARY_HINT%", summary_hint)
    if "%SUMMARY_HINT%" not in str(base_summary or "") and summary_hint:
        rendered = f"{rendered}: {summary_hint}" if rendered else summary_hint
    return rendered.strip() or "Updating file page text with Chuck the File Changer"


def run_file_change(ctx: Any | None = None, payload: dict[str, Any] | None = None):
    """Plan a bounded chunk and save changed pages only in effective live mode.

    ``apply=true`` is necessary but not sufficient for a write: preview intent
    or any effective ``dry_run`` setting keeps execution read-only. Preview and
    apply are recomputed independently; authorization lives in the HTTP/worker
    framework rather than in this pure service entry point.
    """
    payload = payload or {}
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    operation = operation_from_payload(payload)
    targets, source_url = targets_from_payload(payload)

    max_pages = int(_config_value(ctx, "max_pages_per_run", 100) or 100)
    dry_run_default = _bool_value(_config_value(ctx, "dry_run", True), True)
    apply_changes = _bool_value(payload.get("apply", False), False)
    # Apply intent alone cannot override an effective dry-run value.  This pure
    # service does not read the framework's local-safe environment flag; custom
    # queue callers must supply a protective dry-run value themselves.
    dry_run = not apply_changes or _bool_value(payload.get("dry_run", dry_run_default), dry_run_default)

    # Direct callers/tests may inject the narrow adapter interface. JSON queue
    # payloads cannot carry a live Python object and therefore construct Commons.
    wiki = payload.get("wiki_client")
    if wiki is None:
        wiki = WikiClient(
            dry_run=dry_run,
            site_code=COMMONS_SITE_CODE,
            site_family=COMMONS_SITE_FAMILY,
            user_agent_value=str(
                _config_value(ctx, "user_agent", user_agent()) or user_agent()
            ),
        )

    planned: list[FileChangePlanItem] = []
    saved = 0
    errors = 0
    summary = default_summary(operation)

    for target in targets[:max_pages]:
        # Cancellation is outside the per-page error boundary so an operator
        # stop aborts the chunk instead of being reported as an ordinary page error.
        if ctx is not None and hasattr(ctx, "check_cancelled"):
            ctx.check_cancelled()
        try:
            old_text = wiki.get_text(target.title)
            item = plan_target(target, operation, old_text)
            if item.changed and not dry_run:
                # Planning always precedes mutation. The stored item retains
                # ``changed`` status; ``saved_count`` distinguishes live writes.
                wiki.save_text(target.title, item.new_text, edit_summary_for_target(summary, target))
                saved += 1
            planned.append(item)
        except Exception as exc:
            errors += 1
            planned.append(
                FileChangePlanItem(
                    title=target.title,
                    status="error",
                    error=str(exc),
                )
            )

    changed = sum(1 for item in planned if item.changed)
    # ``target_count`` reports the resolved source size, while ``planned_count``
    # reflects the configured per-run slice actually inspected by this chunk.
    return {
        "status": "ok" if errors == 0 else "error",
        "started_at": started_at,
        "dry_run": dry_run,
        "apply_requested": apply_changes,
        "source_url": source_url,
        "site": "commons.wikimedia.org",
        "target_count": len(targets),
        "planned_count": len(planned),
        "changed_count": changed,
        "saved_count": saved,
        "error_count": errors,
        "operation": operation.as_dict(),
        "items": [item.as_dict() for item in planned],
    }
