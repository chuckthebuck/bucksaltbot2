"""Authenticated browser API for Temporary Account Finder."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from .service import FinderError, check_access, find_connected_accounts


MODULE_NAME = "temporary_account_finder"
blueprint = Blueprint(
    MODULE_NAME,
    __name__,
    url_prefix=f"/api/v1/modules/{MODULE_NAME}",
)


def _username() -> str | None:
    """Return the authenticated framework-session username, if present."""
    value = session.get("username")
    return str(value).strip() if value else None


def _has_access(username: str) -> bool:
    """Require normal module discoverability before the stronger wiki check."""
    try:
        from app import is_maintainer
        from router.module_registry import user_has_module_access

        return user_has_module_access(
            MODULE_NAME,
            username,
            is_maintainer=is_maintainer(username),
        )
    except Exception:
        return False


def _require_access():
    """Return the current username or a ready framework-access denial."""
    username = _username()
    if not username:
        return None, (
            jsonify({"detail": "Not authenticated", "code": "not_authenticated"}),
            401,
        )
    if not _has_access(username):
        return None, (
            jsonify({"detail": "Forbidden", "code": "module_access_required"}),
            403,
        )
    return username, None


def _finder_error(exc: FinderError):
    """Translate one user-safe service error into its JSON HTTP response."""
    return jsonify({"detail": exc.detail, "code": exc.code}), exc.status_code


@blueprint.after_request
def _prevent_private_result_caching(response):
    """Keep investigation results out of browser and intermediary caches."""
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@blueprint.get("/api/access")
def access_api():
    """Check the OAuth actor's current reveal access on one selected wiki."""
    username, denied = _require_access()
    if denied:
        return denied
    try:
        payload = check_access(
            request.args.get("wiki", ""),
            expected_username=username or "",
            access_token=session.get("access_token"),
        )
        return jsonify(payload)
    except FinderError as exc:
        return _finder_error(exc)


@blueprint.post("/api/search")
def search_api():
    """Return connected temporary accounts for a bounded input list."""
    username, denied = _require_access()
    if denied:
        return denied
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(
            {"detail": "Request body must be a JSON object.", "code": "invalid_request"}
        ), 400
    unknown = sorted(set(payload) - {"wiki", "accounts", "include_ips"})
    if unknown:
        return jsonify(
            {
                "detail": f"Unsupported request field(s): {', '.join(unknown)}",
                "code": "invalid_request",
            }
        ), 400
    include_ips = payload.get("include_ips", False)
    if not isinstance(include_ips, bool):
        return jsonify(
            {
                "detail": "include_ips must be a boolean.",
                "code": "invalid_request",
            }
        ), 400
    try:
        result = find_connected_accounts(
            str(payload.get("wiki") or ""),
            payload.get("accounts") or "",
            expected_username=username or "",
            access_token=session.get("access_token"),
            include_ips=include_ips,
        )
        return jsonify(result)
    except FinderError as exc:
        return _finder_error(exc)
