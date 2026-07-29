"""Authenticated Saltlick browser API."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from .codegen import render_jobs_py, render_module_toml
from .spec import WorkflowSpec


blueprint = Blueprint(
    "saltlick",
    __name__,
    url_prefix="/api/v1/modules/saltlick",
)
MODULE_NAME = "saltlick"


class ActiveRunError(RuntimeError):
    """Raised when the live Saltlick job already has an active run."""

    def __init__(self, run_ids: list[int]):
        self.run_ids = run_ids
        super().__init__("A live Saltlick run is already active")


def _username() -> str | None:
    value = session.get("username")
    return str(value).strip() if value else None


def _has_right(username: str, right: str) -> bool:
    try:
        from router.authz import user_has_module_right

        return user_has_module_right(username, MODULE_NAME, right)
    except Exception:
        return False


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
        for right in ("manage", "run_jobs", "apply_changes")
    )


def _require_access():
    username = _username()
    if not username:
        return None, (jsonify({"detail": "Not authenticated"}), 401)
    if not _has_access(username):
        return None, (jsonify({"detail": "Forbidden"}), 403)
    return username, None


def _can_preview(username: str) -> bool:
    try:
        from router.routes import _can_run_module_jobs

        if _can_run_module_jobs(username, MODULE_NAME):
            return True
    except Exception:
        pass
    return _has_right(username, "run_jobs") or _has_right(username, "manage")


def _can_apply(username: str) -> bool:
    return _has_right(username, "apply_changes") or _has_right(username, "manage")


def _workflow_from_request(*, allow_confirmation: bool = False) -> tuple[WorkflowSpec, dict]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    allowed = {"recipe", "inputs", "arguments"}
    if allow_confirmation:
        allowed.add("confirm_live")
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unsupported request field(s): {', '.join(unknown)}")
    from .spec import recipe_with_invocation

    invocation = {
        "inputs": payload.get("inputs"),
        "arguments": payload.get("arguments"),
    }
    workflow = WorkflowSpec.from_dict(
        recipe_with_invocation(payload.get("recipe"), **invocation)
    )
    return workflow, invocation


def _enqueue(
    workflow: WorkflowSpec,
    *,
    username: str,
    live: bool,
    invocation: dict | None = None,
) -> int:
    from module_tasks import process_module_job_run
    from router.module_registry import (
        ModuleJobConcurrencyError,
        create_module_job_run,
    )

    job_name = "apply" if live else "preview"
    try:
        run_id = create_module_job_run(
            MODULE_NAME,
            job_name,
            trigger_type="manual",
            triggered_by=username,
            payload={
                "recipe": workflow.as_dict(),
                "inputs": (invocation or {}).get("inputs"),
                "arguments": (invocation or {}).get("arguments"),
                "confirm_live": bool(live),
            },
            concurrency_policy="forbid" if live else "allow",
        )
    except ModuleJobConcurrencyError as exc:
        raise ActiveRunError(exc.active_run_ids) from exc
    process_module_job_run.delay(run_id)
    return run_id


@blueprint.get("/auth")
def auth_api():
    username, denied = _require_access()
    if denied:
        return denied
    return jsonify(
        {
            "username": username,
            "can_preview": _can_preview(username or ""),
            "can_apply": _can_apply(username or ""),
            "can_manage": _has_right(username or "", "manage"),
        }
    )


@blueprint.post("/validate")
def validate_api():
    _, denied = _require_access()
    if denied:
        return denied
    try:
        workflow, _invocation = _workflow_from_request()
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400
    return jsonify(
        {
            "ok": True,
            "recipe": workflow.as_dict(),
            "jobs_py": render_jobs_py(workflow),
            "module_toml": render_module_toml(workflow),
        }
    )


@blueprint.post("/preview")
def preview_api():
    username, denied = _require_access()
    if denied:
        return denied
    if not _can_preview(username or ""):
        return jsonify({"detail": "Forbidden: run_jobs right required"}), 403
    try:
        workflow, invocation = _workflow_from_request()
        run_id = _enqueue(
            workflow,
            username=username or "",
            live=False,
            invocation=invocation,
        )
    except ActiveRunError as exc:
        return jsonify({"detail": str(exc), "active_run_ids": exc.run_ids}), 409
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400
    return jsonify({"status": "queued", "run_id": run_id, "job": "preview"}), 202


@blueprint.post("/apply")
def apply_api():
    username, denied = _require_access()
    if denied:
        return denied
    if not _can_apply(username or ""):
        return jsonify({"detail": "Forbidden: apply_changes right required"}), 403
    try:
        workflow, invocation = _workflow_from_request(allow_confirmation=True)
        payload = request.get_json(silent=True) or {}
        if payload.get("confirm_live") is not True:
            return jsonify({"detail": "Live run requires confirm_live=true"}), 400
        run_id = _enqueue(
            workflow,
            username=username or "",
            live=True,
            invocation=invocation,
        )
    except ActiveRunError as exc:
        return jsonify({"detail": str(exc), "active_run_ids": exc.run_ids}), 409
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400
    return jsonify({"status": "queued", "run_id": run_id, "job": "apply"}), 202


@blueprint.get("/runs/<int:run_id>")
def run_api(run_id: int):
    username, denied = _require_access()
    if denied:
        return denied
    from router.module_registry import get_module_job_run

    run = get_module_job_run(run_id)
    if run is None or run.get("module_name") != MODULE_NAME:
        return jsonify({"detail": "Run not found"}), 404
    owner = str(run.get("triggered_by") or "")
    if owner and owner != username and not _has_right(username or "", "manage"):
        return jsonify({"detail": "Forbidden"}), 403
    return jsonify(run)
