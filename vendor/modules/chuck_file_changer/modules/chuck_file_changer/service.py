from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from .config import COMMONS_SITE_CODE, COMMONS_SITE_FAMILY, http_headers, user_agent
from .models import FileChangePlanItem
from .planner import default_summary, operation_from_payload, plan_target
from .quarry import parse_targets_text, quarry_result_url
from .wiki import WikiClient


def _config_value(ctx: Any | None, key: str, default: Any) -> Any:
    if ctx is None or not hasattr(ctx, "config"):
        return default
    cfg = ctx.config
    if hasattr(cfg, "get"):
        return cfg.get(key, default)
    return default


def _bool_value(value: Any, default: bool) -> bool:
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
    source_text = str(payload.get("targets_text") or payload.get("source_text") or "")
    quarry_input = str(payload.get("quarry") or payload.get("quarry_url") or "").strip()

    if quarry_input:
        url = quarry_result_url(quarry_input)
        if not url:
            raise ValueError("Quarry source must be a query URL, run URL, query ID, or run:ID")
        response = requests.get(url, headers=http_headers(), timeout=30)
        response.raise_for_status()
        return parse_targets_text(response.text), url

    return parse_targets_text(source_text), None


def run_file_change(ctx: Any | None = None, payload: dict[str, Any] | None = None):
    payload = payload or {}
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    operation = operation_from_payload(payload)
    targets, source_url = targets_from_payload(payload)

    max_pages = int(_config_value(ctx, "max_pages_per_run", 100) or 100)
    dry_run_default = _bool_value(_config_value(ctx, "dry_run", True), True)
    apply_changes = _bool_value(payload.get("apply", False), False)
    dry_run = not apply_changes or _bool_value(payload.get("dry_run", dry_run_default), dry_run_default)

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
        try:
            old_text = wiki.get_text(target.title)
            item = plan_target(target, operation, old_text)
            if item.changed and not dry_run:
                wiki.save_text(target.title, item.new_text, summary)
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
