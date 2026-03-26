"""MediaWiki API functions for fetching revision metadata and contributions."""

import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import requests

from app import flask_app as app
from router.diff_state import (
    _ACCOUNT_ROLLBACK_MAX_LIMIT,
    _MW_DEBUG_BODY_MAX,
    _ROLLBACKABLE_WINDOW_LIMIT,
)


def _extract_oldid(diff_value):
    if diff_value is None:
        raise ValueError("Missing diff parameter")

    raw = str(diff_value).strip()

    if not raw:
        raise ValueError("Missing diff parameter")

    if raw.isdigit():
        return int(raw)

    parsed = urlparse(raw)
    oldid = parse_qs(parsed.query).get("oldid", [None])[0]

    if oldid and str(oldid).strip().isdigit():
        return int(str(oldid).strip())

    raise ValueError("diff must be a revision id or URL containing oldid")


def _normalize_target_user_input(raw_value):
    cleaned = str(raw_value or "").strip()

    if cleaned.lower().startswith("user:"):
        cleaned = cleaned[5:].strip()

    if len(cleaned) >= 2 and (
        (cleaned[0] == '"' and cleaned[-1] == '"')
        or (cleaned[0] == "'" and cleaned[-1] == "'")
    ):
        cleaned = cleaned[1:-1].strip()

    return " ".join(cleaned.replace("_", " ").split())


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_diff_author_and_timestamp(oldid, debug_callback=None):
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "revisions",
        "revids": str(oldid),
        "rvprop": "ids|user|timestamp",
        "format": "json",
    }

    started = time.perf_counter()
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if callable(debug_callback):
            debug_callback(
                {
                    "kind": "revisions",
                    "params": params,
                    "status_code": resp.status_code,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "response_snippet": resp.text[:_MW_DEBUG_BODY_MAX],
                }
            )
    except requests.RequestException as e:
        if callable(debug_callback):
            debug_callback(
                {
                    "kind": "revisions",
                    "params": params,
                    "error": f"{type(e).__name__}: {e}",
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                }
            )
        app.logger.error("Failed to fetch revision metadata for oldid %s: %s", oldid, e)
        raise ValueError(f"Failed to fetch revision metadata: {e}") from e

    pages = data.get("query", {}).get("pages", {})

    for page in pages.values():
        revisions = page.get("revisions") or []

        if revisions:
            revision = revisions[0]
            user = revision.get("user")
            timestamp = revision.get("timestamp")

            if user and timestamp:
                return {
                    "user": user,
                    "timestamp": timestamp,
                }

    raise ValueError("Revision not found for provided diff")


def fetch_rollbackable_window_end_timestamp(
    target_user,
    start_timestamp,
    limit=_ROLLBACKABLE_WINDOW_LIMIT,
    debug_callback=None,
):
    """Return timestamp of the oldest edit in the latest rollbackable window."""
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "usercontribs",
        "ucuser": target_user,
        "uclimit": str(min(_ROLLBACKABLE_WINDOW_LIMIT, int(limit))),
        "ucprop": "ids|title|timestamp",
        "ucshow": "top",
        "ucstart": _utc_now_iso(),
        "ucend": start_timestamp,
        "ucdir": "older",
        "format": "json",
    }

    started = time.perf_counter()
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if callable(debug_callback):
            debug_callback(
                {
                    "kind": "usercontribs-window",
                    "params": params,
                    "status_code": resp.status_code,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "response_snippet": resp.text[:_MW_DEBUG_BODY_MAX],
                }
            )
    except requests.RequestException as e:
        if callable(debug_callback):
            debug_callback(
                {
                    "kind": "usercontribs-window",
                    "params": params,
                    "error": f"{type(e).__name__}: {e}",
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                }
            )
        raise ValueError(f"Failed to fetch rollbackable contribution window: {e}") from e

    contribs = data.get("query", {}).get("usercontribs", [])
    if not contribs:
        return None

    oldest = contribs[-1].get("timestamp")
    return oldest or None


def fetch_recent_rollbackable_contribs(
    target_user,
    limit=_ACCOUNT_ROLLBACK_MAX_LIMIT,
    debug_callback=None,
):
    """Return latest rollbackable contributions for a target account."""
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "usercontribs",
        "ucuser": target_user,
        "uclimit": str(min(_ACCOUNT_ROLLBACK_MAX_LIMIT, int(limit))),
        "ucprop": "ids|title|timestamp",
        "ucshow": "top",
        "ucstart": _utc_now_iso(),
        "ucdir": "older",
        "format": "json",
    }

    started = time.perf_counter()
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if callable(debug_callback):
            debug_callback(
                {
                    "kind": "usercontribs-account",
                    "params": params,
                    "status_code": resp.status_code,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "response_snippet": resp.text[:_MW_DEBUG_BODY_MAX],
                }
            )
    except requests.RequestException as e:
        if callable(debug_callback):
            debug_callback(
                {
                    "kind": "usercontribs-account",
                    "params": params,
                    "error": f"{type(e).__name__}: {e}",
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                }
            )
        raise ValueError(f"Failed to fetch recent rollbackable contributions: {e}") from e

    contribs = data.get("query", {}).get("usercontribs", [])
    results = []

    for edit in contribs:
        title = edit.get("title")
        if not title:
            continue
        results.append({"title": title, "user": target_user})

    return results


def iter_contribs_after_timestamp(
    target_user,
    start_timestamp,
    limit=None,
    end_timestamp=None,
    rollbackable_only=False,
    debug_callback=None,
):
    url = "https://commons.wikimedia.org/w/api.php"

    continue_params = None
    yielded = 0

    while True:
        remaining = None

        if limit is not None:
            remaining = max(limit - yielded, 0)

            if remaining == 0:
                break

        params = {
            "action": "query",
            "list": "usercontribs",
            "ucuser": target_user,
            "uclimit": str(min(500, remaining)) if remaining is not None else "500",
            "ucprop": "ids|title|timestamp",
            "ucstart": start_timestamp,
            "ucdir": "newer",
            "format": "json",
        }

        if rollbackable_only:
            params["ucshow"] = "top"

        if end_timestamp:
            params["ucend"] = end_timestamp

        if continue_params:
            params.update(continue_params)

        started = time.perf_counter()
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if callable(debug_callback):
                debug_callback(
                    {
                        "kind": "usercontribs",
                        "params": params,
                        "status_code": resp.status_code,
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                        "response_snippet": resp.text[:_MW_DEBUG_BODY_MAX],
                        "continue": data.get("continue"),
                    }
                )
        except requests.RequestException as e:
            if callable(debug_callback):
                debug_callback(
                    {
                        "kind": "usercontribs",
                        "params": params,
                        "error": f"{type(e).__name__}: {e}",
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    }
                )
            app.logger.error(
                "Failed to fetch contributions for user %s after timestamp %s: %s",
                target_user,
                start_timestamp,
                e,
            )
            raise ValueError(f"Failed to fetch user contributions: {e}") from e

        contribs = data.get("query", {}).get("usercontribs", [])

        for edit in contribs:
            if edit.get("timestamp") and edit["timestamp"] > start_timestamp:
                yielded += 1
                yield {"title": edit["title"], "user": target_user}

                if limit is not None and yielded >= limit:
                    break

        if limit is not None and yielded >= limit:
            break

        if not data.get("continue"):
            break

        continue_params = data["continue"]

        time.sleep(0.1)

        if yielded >= 10000:
            break


def fetch_contribs_after_timestamp(target_user, start_timestamp, limit=None):
    return list(iter_contribs_after_timestamp(target_user, start_timestamp, limit=limit))
