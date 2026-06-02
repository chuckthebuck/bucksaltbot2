from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from .quarry import parse_targets_text, quarry_result_url

blueprint = Blueprint("chuck_file_changer", __name__)
MODULE_NAME = "chuck_file_changer"
JOB_NAME = "file-change"


def _username() -> str | None:
    username = session.get("username")
    return str(username).strip() if username else None


def _has_access(username: str) -> bool:
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
    return any(
        _has_right(username, right)
        for right in ("manage", "run_jobs", "edit_config", "apply_changes")
    )


def _has_right(username: str, right: str) -> bool:
    try:
        from router.authz import user_has_module_right

        return user_has_module_right(username, MODULE_NAME, right)
    except Exception:
        return False


def _require_access():
    username = _username()
    if not username:
        return None, (jsonify({"detail": "Not authenticated"}), 401)
    if not _has_access(username):
        return None, (jsonify({"detail": "Forbidden"}), 403)
    return username, None


def _can_apply(username: str) -> bool:
    return _has_right(username, "apply_changes") or _has_right(username, "manage")


def _enqueue_file_change(payload: dict, *, username: str):
    from module_tasks import process_module_job_run
    from router.module_registry import create_module_job_run

    run_id = create_module_job_run(
        MODULE_NAME,
        JOB_NAME,
        trigger_type="manual",
        triggered_by=username,
        payload=payload,
    )
    process_module_job_run.delay(run_id)
    return run_id


@blueprint.get("/api/auth")
def auth_api():
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
    username, denied = _require_access()
    if denied:
        return denied

    payload = request.get_json(silent=True) or {}
    payload["dry_run"] = True
    payload["apply"] = False
    try:
        run_id = _enqueue_file_change(payload, username=username or "")
        return jsonify({"run_id": run_id, "status": "queued", "job": JOB_NAME}), 202
    except Exception as exc:
        return jsonify({"detail": str(exc)}), 400


@blueprint.post("/api/apply")
def apply_api():
    username, denied = _require_access()
    if denied:
        return denied
    if not _can_apply(username or ""):
        return jsonify({"detail": "Forbidden: apply_changes right required"}), 403

    payload = request.get_json(silent=True) or {}
    payload["apply"] = True
    try:
        run_id = _enqueue_file_change(payload, username=username or "")
        return jsonify({"run_id": run_id, "status": "queued", "job": JOB_NAME}), 202
    except Exception as exc:
        return jsonify({"detail": str(exc)}), 400


@blueprint.get("/api/jobs/<int:run_id>")
def job_status_api(run_id: int):
    username, denied = _require_access()
    if denied:
        return denied

    from router.module_registry import get_module_job_run

    run = get_module_job_run(run_id)
    if run is None or run.get("module_name") != MODULE_NAME:
        return jsonify({"detail": "Run not found"}), 404
    if run.get("triggered_by") and run.get("triggered_by") != username and not _has_right(username or "", "manage"):
        return jsonify({"detail": "Forbidden"}), 403
    return jsonify(run)
