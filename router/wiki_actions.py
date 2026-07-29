"""Framework-owned execution for declarative MediaWiki action plans."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


SUPPORTED_WIKI_ACTIONS = frozenset(
    {
        "mediawiki.page.purge",
    }
)


def _wiki_target(action: dict[str, Any]) -> tuple[str, str]:
    target = action.get("target") or {}
    wiki = target.get("wiki") or {}
    code = str(wiki.get("code") or "commons").strip().lower()
    family = str(wiki.get("family") or "commons").strip().lower()
    return code, family


def _purge_page(
    site: Any,
    *,
    target: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    import pywikibot

    title = str(target.get("title") or "").strip()
    namespace = int(target.get("namespace", 0))
    page = pywikibot.Page(site, title, ns=namespace)
    request_parameters: dict[str, Any] = {
        "action": "purge",
        "titles": page.title(),
    }
    if bool(params.get("forcelinkupdate", False)):
        request_parameters["forcelinkupdate"] = 1
    if bool(params.get("forcerecursivelinkupdate", False)):
        request_parameters["forcerecursivelinkupdate"] = 1
    response = site.simple_request(**request_parameters).submit()
    return {
        "request": request_parameters,
        "response": response,
    }


def execute_action_plan(
    actions: Iterable[dict[str, Any]],
    *,
    site_factory: Callable[[str, str], Any],
    dry_run: bool = True,
    allowed_types: Iterable[str] = (),
) -> dict[str, Any]:
    """Preview or execute a bounded plan through framework-reviewed handlers."""
    allowed = set(allowed_types)
    unsupported_declared = sorted(allowed - SUPPORTED_WIKI_ACTIONS)
    if unsupported_declared:
        raise ValueError(
            "framework does not support declared action type(s): "
            + ", ".join(unsupported_declared)
        )

    items: list[dict[str, Any]] = []
    completed = errors = 0
    for index, raw_action in enumerate(actions):
        action = dict(raw_action)
        action_type = str(action.get("type") or "")
        target = dict(action.get("target") or {})
        params = dict(action.get("params") or {})
        item: dict[str, Any] = {
            "index": index,
            "type": action_type,
            "target": target,
            "params": params,
            "status": "planned" if dry_run else "running",
        }
        try:
            if action_type not in allowed:
                raise ValueError(
                    f"action type is not declared by the module: {action_type}"
                )
            if action_type not in SUPPORTED_WIKI_ACTIONS:
                raise ValueError(
                    f"unsupported framework action type: {action_type}"
                )
            if dry_run:
                items.append(item)
                continue
            code, family = _wiki_target(action)
            site = site_factory(code, family)
            if action_type == "mediawiki.page.purge":
                item["result"] = _purge_page(
                    site,
                    target=target,
                    params=params,
                )
            item["status"] = "completed"
            completed += 1
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)
            errors += 1
        items.append(item)

    return {
        "ok": errors == 0,
        "dry_run": bool(dry_run),
        "planned_count": len(items),
        "completed_count": completed,
        "error_count": errors,
        "items": items,
    }
