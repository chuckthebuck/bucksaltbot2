from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import requests

from .config import COMMONS_API_URL, http_headers
from .models import FileChangeTarget
from .quarry import dedupe_targets, normalize_file_title

API_BATCH_LIMIT = 500
DEFAULT_SOURCE_LIMIT = 5000
MAX_SOURCE_LIMIT = 50000

SOURCE_MODES = {"user", "category", "page", "search"}


def source_mode_from_payload(payload: dict[str, Any]) -> str:
    return str(
        payload.get("source_mode")
        or payload.get("file_source_mode")
        or payload.get("vfc_source_mode")
        or ""
    ).strip().lower()


def has_vfc_source(payload: dict[str, Any]) -> bool:
    return source_mode_from_payload(payload) in SOURCE_MODES


def source_url_for_payload(payload: dict[str, Any]) -> str:
    mode = source_mode_from_payload(payload)
    target = source_target(payload)
    query = urlencode({"source_mode": mode, "target": target})
    return f"{COMMONS_API_URL}?{query}"


def source_target(payload: dict[str, Any]) -> str:
    return str(
        payload.get("source_target")
        or payload.get("target")
        or payload.get("vfc_target")
        or ""
    ).strip()


def source_limit(payload: dict[str, Any]) -> int:
    try:
        value = int(payload.get("source_limit") or payload.get("limit") or DEFAULT_SOURCE_LIMIT)
    except (TypeError, ValueError):
        value = DEFAULT_SOURCE_LIMIT
    return max(1, min(value, MAX_SOURCE_LIMIT))


def resolve_vfc_source(payload: dict[str, Any]) -> tuple[list[FileChangeTarget], str]:
    mode = source_mode_from_payload(payload)
    target = source_target(payload)
    if mode not in SOURCE_MODES:
        raise ValueError("Source mode must be user, category, page, or search")
    if not target:
        raise ValueError("Source target is required")

    if mode == "user":
        targets = _resolve_user_uploads(target, payload)
    elif mode == "category":
        targets = _resolve_category(target, payload)
    elif mode == "page":
        targets = _resolve_page_images(target, payload)
    else:
        targets = _resolve_search(target, payload)
    return dedupe_targets(targets), source_url_for_payload(payload)


def _get(params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(
        COMMONS_API_URL,
        params={"format": "json", "formatversion": 2, **params},
        headers=http_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _continue_params(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("continue")
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items() if value is not None}
    return {}


def _source_sort(payload: dict[str, Any]) -> str:
    return str(payload.get("source_sort") or payload.get("sort") or "newest").strip().lower()


def _resolve_user_uploads(user: str, payload: dict[str, Any]) -> list[FileChangeTarget]:
    # The UI often receives a copied ``User:Name`` page title.  logevents
    # expects the username itself, not its namespace-qualified page title.
    username = user.strip()
    if username.lower().startswith("user:"):
        username = username[5:].strip()
    if not username:
        raise ValueError("Uploader is required")

    remaining = source_limit(payload)
    params: dict[str, Any] = {
        "action": "query",
        "list": "logevents",
        "leprop": "title|timestamp|type|user",
        # ``leaction=upload/upload`` omits re-uploads (``overwrite``), even
        # though they are uploads by the selected account.  Filter by type and
        # accept both actions below so the source is complete.
        "letype": "upload",
        "leuser": username,
        "lelimit": min(API_BATCH_LIMIT, remaining),
        "ledir": "newer" if _source_sort(payload) == "oldest" else "older",
    }
    params.update(_continue_params(payload))

    targets: list[FileChangeTarget] = []
    while remaining > 0:
        data = _get(params)
        for event in data.get("query", {}).get("logevents", []):
            if event.get("action") not in {"upload", "overwrite"} or not event.get("title"):
                continue
            targets.append(
                FileChangeTarget(
                    title=normalize_file_title(event["title"]),
                    user=username,
                    summary_hint=event.get("timestamp"),
                )
            )
            remaining -= 1
            if remaining <= 0:
                break
        cont = data.get("continue")
        if not cont or remaining <= 0:
            break
        params.update(cont)
        params["lelimit"] = min(API_BATCH_LIMIT, remaining)
    return targets


def _resolve_category(category: str, payload: dict[str, Any]) -> list[FileChangeTarget]:
    title = category if ":" in category else f"Category:{category}"
    sort = _source_sort(payload)
    params: dict[str, Any] = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": title,
        "cmtype": "file",
        "cmprop": "title|timestamp",
        "cmlimit": min(API_BATCH_LIMIT, source_limit(payload)),
        "cmdir": "asc" if sort in {"oldest", "name_asc"} else "desc",
    }
    if sort in {"oldest", "newest"}:
        params["cmsort"] = "timestamp"
        params["cmnamespace"] = 6
    params.update(_continue_params(payload))
    return _collect_paged_targets(params, "categorymembers", source_limit(payload))


def _resolve_page_images(page: str, payload: dict[str, Any]) -> list[FileChangeTarget]:
    remaining = source_limit(payload)
    params: dict[str, Any] = {
        "action": "query",
        "prop": "images",
        "titles": page,
        "imlimit": min(API_BATCH_LIMIT, remaining),
        "imdir": "ascending" if _source_sort(payload) in {"oldest", "name_asc"} else "descending",
    }
    params.update(_continue_params(payload))

    targets: list[FileChangeTarget] = []
    while remaining > 0:
        data = _get(params)
        for page_data in data.get("query", {}).get("pages", []):
            if page_data.get("missing") or page_data.get("invalid"):
                raise ValueError("Page source does not exist or is invalid")
            for image in page_data.get("images", []):
                if not image.get("title"):
                    continue
                targets.append(FileChangeTarget(title=normalize_file_title(image["title"])))
                remaining -= 1
                if remaining <= 0:
                    break
        cont = data.get("continue")
        if not cont or remaining <= 0:
            break
        params.update(cont)
        params["imlimit"] = min(API_BATCH_LIMIT, remaining)
    return targets


def _resolve_search(query: str, payload: dict[str, Any]) -> list[FileChangeTarget]:
    params: dict[str, Any] = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": 6,
        "srlimit": min(API_BATCH_LIMIT, source_limit(payload)),
    }
    params.update(_continue_params(payload))
    return _collect_paged_targets(params, "search", source_limit(payload))


def _collect_paged_targets(
    params: dict[str, Any],
    result_key: str,
    limit: int,
) -> list[FileChangeTarget]:
    remaining = limit
    targets: list[FileChangeTarget] = []
    while remaining > 0:
        data = _get(params)
        for record in data.get("query", {}).get(result_key, []):
            if not record.get("title"):
                continue
            targets.append(
                FileChangeTarget(
                    title=normalize_file_title(record["title"]),
                    summary_hint=record.get("timestamp"),
                )
            )
            remaining -= 1
            if remaining <= 0:
                break
        cont = data.get("continue")
        if not cont or remaining <= 0:
            break
        params.update(cont)
        if result_key == "categorymembers":
            params["cmlimit"] = min(API_BATCH_LIMIT, remaining)
        if result_key == "search":
            params["srlimit"] = min(API_BATCH_LIMIT, remaining)
    return targets
