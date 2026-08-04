"""Authenticated browser API for previewing and queueing file-page changes.

Routes authorize access before parsing work, force preview requests into dry
mode, require an explicit module right for apply requests, and expose only
owned durable job records unless the caller has the module ``manage`` right.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from .quarry import parse_targets_text, quarry_result_url

blueprint = Blueprint("chuck_file_changer", __name__)
MODULE_NAME = "chuck_file_changer"
JOB_NAME = "file-change"


def _username() -> str | None:
    """Return the normalized framework-session username, if authenticated."""
    username = session.get("username")
    return str(username).strip() if username else None


def _has_access(username: str) -> bool:
    """Allow framework module access or any broad File Changer capability.

    Compatibility with explicit module-access rows and module-right grants is
    kept here so users with a narrowly delegated right can still load the UI.
    """
    try:
        from app import is_maintainer
        from router.module_registry import user_has_module_access

        if user_has_module_access(
            MODULE_NAME,
            username,
            is_maintainer=is_maintainer(username),
        ):
            return True
    except Exception:
        pass
    # The access check is deliberately broader than apply authorization; route-
    # specific checks below decide which actions an admitted user may perform.
    return any(
        _has_right(username, right)
        for right in ("manage", "run_jobs", "edit_config", "apply_changes")
    )


def _has_right(username: str, right: str) -> bool:
    """Query configured module grants and fail closed on backend errors.

    ``user_has_module_right`` honors a configured global ``manage_modules``
    grant, but it does not add the framework's fixed maintainer hierarchy.
    """
    try:
        from router.authz import user_has_module_right

        return user_has_module_right(username, MODULE_NAME, right)
    except Exception:
        return False


def _require_access():
    """Return the username or a reusable 401/403 Flask response."""
    username = _username()
    if not username:
        return None, (jsonify({"detail": "Not authenticated"}), 401)
    if not _has_access(username):
        return None, (jsonify({"detail": "Forbidden"}), 403)
    return username, None


def _can_apply(username: str) -> bool:
    """Require configured apply/manage authority for potentially live work."""
    return _has_right(username, "apply_changes") or _has_right(username, "manage")


def _enqueue_file_change_batch(payload: dict, *, username: str) -> dict:
    """Persist a target batch, then dispatch one task per durable chunk.

    Database rows are created before Celery receives IDs, so workers never rely
    on a browser-held target list and every dispatched chunk is inspectable.
    """
    from module_tasks import process_chuck_file_change_job

    from .queue import enqueue_file_change_batch

    queued = enqueue_file_change_batch(payload, username=username)
    for job_id in queued["job_ids"]:
        process_chuck_file_change_job.delay(job_id)
    return queued


@blueprint.get("/api/auth")
def auth_api():
    """Return UI capability hints for the authenticated module user.

    These flags control frontend affordances only; apply and job-read routes
    repeat their authorization checks server-side.
    """
    username, denied = _require_access()
    if denied:
        return denied

    return jsonify(
        {
            "username": username,
            "can_view": True,
            "can_apply": _can_apply(username or ""),
            "can_manage": _has_right(username or "", "manage"),
            "can_run_jobs": _has_right(username or "", "run_jobs"),
            "can_edit_config": _has_right(username or "", "edit_config"),
        }
    )


@blueprint.post("/api/targets/parse")
def parse_targets_api():
    """Normalize pasted JSON/CSV/TSV/manual target text without queueing work."""
    _, denied = _require_access()
    if denied:
        return denied

    payload = request.get_json(silent=True) or {}
    try:
        targets = parse_targets_text(str(payload.get("source_text") or ""))
        return jsonify({"targets": [target.as_dict() for target in targets]})
    except Exception as exc:
        return jsonify({"detail": str(exc)}), 400


@blueprint.post("/api/quarry/url")
def quarry_url_api():
    """Convert an allowlisted Quarry identifier or URL to its JSON result URL."""
    _, denied = _require_access()
    if denied:
        return denied

    payload = request.get_json(silent=True) or {}
    url = quarry_result_url(str(payload.get("quarry") or ""))
    if not url:
        return jsonify({"detail": "Invalid Quarry source"}), 400
    return jsonify({"url": url})


@blueprint.post("/api/preview")
def preview_api():
    """Force dry-run semantics and queue the parsed target batch.

    Browser-supplied ``apply`` and ``dry_run`` values are overwritten so this
    route cannot be promoted to a live run by request data.
    """
    username, denied = _require_access()
    if denied:
        return denied

    payload = request.get_json(silent=True) or {}
    payload["dry_run"] = True
    payload["apply"] = False
    try:
        queued = _enqueue_file_change_batch(payload, username=username or "")
        return jsonify({"status": "queued", "job": JOB_NAME, **queued}), 202
    except Exception as exc:
        return jsonify({"detail": str(exc)}), 400


@blueprint.post("/api/apply")
def apply_api():
    """Authorize apply intent and queue a batch for worker-side safety checks.

    Setting ``apply`` expresses live intent; the service's module/payload
    ``dry_run`` setting may still downgrade execution to a preview. This custom
    queue does not run through ``module_runner``, so the framework's
    ``CHUCKBOT_LOCAL_SAFE_MODE`` override is not injected here; local operators
    must use preview only.
    """
    username, denied = _require_access()
    if denied:
        return denied
    if not _can_apply(username or ""):
        return jsonify({"detail": "Forbidden: apply_changes right required"}), 403

    payload = request.get_json(silent=True) or {}
    payload["apply"] = True
    try:
        queued = _enqueue_file_change_batch(payload, username=username or "")
        return jsonify({"status": "queued", "job": JOB_NAME, **queued}), 202
    except Exception as exc:
        return jsonify({"detail": str(exc)}), 400


@blueprint.get("/api/jobs/<int:run_id>")
def job_status_api(run_id: int):
    """Return an owned durable job, or any module job to a manager."""
    username, denied = _require_access()
    if denied:
        return denied

    from .queue import get_file_change_job

    run = get_file_change_job(run_id)
    if run is None:
        return jsonify({"detail": "Run not found"}), 404
    # Ownership is checked after resolving the module-local row. Managers need
    # cross-user visibility for operations; ordinary users see only their jobs.
    if run.get("triggered_by") and run.get("triggered_by") != username and not _has_right(username or "", "manage"):
        return jsonify({"detail": "Forbidden"}), 403
    return jsonify(run)
