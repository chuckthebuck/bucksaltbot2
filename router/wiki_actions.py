"""Framework-owned, batched execution for declarative Pywikibot action plans."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


# This is deliberately a reviewed catalogue, rather than an escape hatch that
# invokes an arbitrary Pywikibot method supplied by a module.  Saltlicks may
# only emit an action they declare in their immutable contract.
_PAGE_OPERATIONS = frozenset(
    {
        "purge",
        "edit",
        "delete",
        "undelete",
        "move",
        "protect",
        "touch",
        "watch",
        "unwatch",
        "rollback",
    }
)
SUPPORTED_WIKI_ACTIONS = frozenset(
    {
        f"{prefix}.page.{operation}"
        for prefix in ("mediawiki", "pywikibot")
        for operation in _PAGE_OPERATIONS
    }
)


def _wiki_target(action: dict[str, Any]) -> tuple[str, str]:
    target = action.get("target") or {}
    wiki = target.get("wiki") or {}
    code = str(wiki.get("code") or "commons").strip().lower()
    family = str(wiki.get("family") or "commons").strip().lower()
    return code, family


def _page(site: Any, target: dict[str, Any]):
    import pywikibot

    title = str(target.get("title") or "").strip()
    if not title:
        raise ValueError("page action target.title is required")
    return pywikibot.Page(site, title, ns=int(target.get("namespace", 0)))


def _purge_page(site: Any, *, target: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    page = _page(site, target)
    request_parameters: dict[str, Any] = {"action": "purge", "titles": page.title()}
    if bool(params.get("forcelinkupdate", False)):
        request_parameters["forcelinkupdate"] = 1
    if bool(params.get("forcerecursivelinkupdate", False)):
        request_parameters["forcerecursivelinkupdate"] = 1
    response = site.simple_request(**request_parameters).submit()
    return {"request": request_parameters, "response": response}


def _page_action(site: Any, operation: str, *, target: dict[str, Any], params: dict[str, Any]) -> Any:
    if operation == "purge":
        return _purge_page(site, target=target, params=params)
    page = _page(site, target)
    reason = str(params.get("reason") or params.get("summary") or "")
    if operation == "edit":
        text = params.get("text")
        if text is None:
            raise ValueError("edit action params.text is required")
        return page.put(str(text), summary=reason, minor=bool(params.get("minor", False)), botflag=bool(params.get("bot", True)))
    if operation == "delete":
        return page.delete(reason=reason, prompt=False)
    if operation == "undelete":
        return page.undelete(reason=reason)
    if operation == "move":
        new_title = str(params.get("new_title") or "").strip()
        if not new_title:
            raise ValueError("move action params.new_title is required")
        return page.move(new_title, reason=reason, movetalk=bool(params.get("move_talk", True)), noredirect=bool(params.get("no_redirect", False)))
    if operation == "protect":
        protections = params.get("protections")
        if not isinstance(protections, dict) or not protections:
            raise ValueError("protect action params.protections must be a non-empty object")
        protect_kwargs: dict[str, Any] = {
            "reason": reason,
            "protections": protections,
        }
        if params.get("expiry") is not None:
            protect_kwargs["expiry"] = params["expiry"]
        return page.protect(**protect_kwargs)
    if operation == "touch":
        return page.touch(botflag=bool(params.get("bot", True)))
    if operation in {"watch", "unwatch"}:
        return page.watch(unwatch=operation == "unwatch")
    if operation == "rollback":
        user = str(params.get("user") or "").strip()
        if not user:
            raise ValueError("rollback action params.user is required")
        return site.rollbackpage(
            page,
            user=user,
            summary=reason,
            bot=bool(params.get("bot", True)),
        )
    raise ValueError(f"unsupported framework page operation: {operation}")


def _operation(action_type: str) -> str:
    _prefix, _page_kind, operation = action_type.split(".", 2)
    return operation


def execute_action_plan(
    actions: Iterable[dict[str, Any]],
    *,
    site_factory: Callable[[str, str], Any],
    dry_run: bool = True,
    allowed_types: Iterable[str] = (),
    batch_size: int = 50,
    batch_callback: Callable[[int, int, int], None] | None = None,
) -> dict[str, Any]:
    """Preview or execute a bounded plan through reviewed, Redis-ready batches.

    ``batch_callback`` is intentionally storage-agnostic: callers can persist
    progress to their module Redis namespace without exposing Redis to child
    Saltlick scripts.  A batch is also the cancellation/progress boundary.
    """
    allowed = set(allowed_types)
    unsupported_declared = sorted(allowed - SUPPORTED_WIKI_ACTIONS)
    if unsupported_declared:
        raise ValueError("framework does not support declared action type(s): " + ", ".join(unsupported_declared))
    try:
        size = max(1, min(int(batch_size), 500))
    except (TypeError, ValueError):
        raise ValueError("batch_size must be an integer") from None

    pending = [dict(action) for action in actions]
    items: list[dict[str, Any]] = []
    completed = errors = 0
    site_cache: dict[tuple[str, str], Any] = {}
    for batch_start in range(0, len(pending), size):
        batch = pending[batch_start : batch_start + size]
        for offset, action in enumerate(batch):
            index = batch_start + offset
            action_type = str(action.get("type") or "")
            target = dict(action.get("target") or {})
            params = dict(action.get("params") or {})
            item: dict[str, Any] = {"index": index, "type": action_type, "target": target, "params": params, "status": "planned" if dry_run else "running"}
            try:
                if action_type not in allowed:
                    raise ValueError(f"action type is not declared by the module: {action_type}")
                if action_type not in SUPPORTED_WIKI_ACTIONS:
                    raise ValueError(f"unsupported framework action type: {action_type}")
                if dry_run:
                    items.append(item)
                    continue
                key = _wiki_target(action)
                site = site_cache.get(key)
                if site is None:
                    site = site_factory(*key)
                    site_cache[key] = site
                item["result"] = _page_action(site, _operation(action_type), target=target, params=params)
                item["status"] = "completed"
                completed += 1
            except Exception as exc:  # Item failures must not lose the batch.
                item["status"] = "error"
                item["error"] = str(exc)
                errors += 1
            items.append(item)
        if batch_callback is not None:
            batch_callback(batch_start // size + 1, min(batch_start + len(batch), len(pending)), len(pending))

    return {"ok": errors == 0, "dry_run": bool(dry_run), "planned_count": len(items), "completed_count": completed, "error_count": errors, "items": items}
