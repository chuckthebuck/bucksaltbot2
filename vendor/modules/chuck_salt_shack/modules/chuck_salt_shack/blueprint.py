"""Authenticated Salt Shack browser API."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from .codegen import render_jobs_py, render_module_toml
from .contracts import public_contract, validate_arguments, validate_inputs
from .registry import get_saltlick, registry_fingerprint, registry_payload
from .spec import WorkflowSpec


blueprint = Blueprint(
    "chuck_salt_shack",
    __name__,
    url_prefix="/api/v1/modules/chuck_salt_shack",
)
MODULE_NAME = "chuck_salt_shack"


class ActiveRunError(RuntimeError):
    """Raised when the live Saltlick job already has an active run."""

    def __init__(self, run_ids: list[int]):
        """Preserve conflicting run IDs for the HTTP 409 response."""
        self.run_ids = run_ids
        super().__init__("A live Saltlick run is already active")


def _username() -> str | None:
    """Return the normalized framework session username, if authenticated."""
    value = session.get("username")
    return str(value).strip() if value else None


def _has_right(username: str, right: str) -> bool:
    """Query one module-scoped framework right without leaking auth failures."""
    try:
        from router.authz import user_has_module_right

        return user_has_module_right(username, MODULE_NAME, right)
    except Exception:
        return False


def _has_access(username: str) -> bool:
    """Return whether the user may enter Chuck the Salt Shack."""
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
    """Return the current username or a ready Flask denial response."""
    username = _username()
    if not username:
        return None, (jsonify({"detail": "Not authenticated"}), 401)
    if not _has_access(username):
        return None, (jsonify({"detail": "Forbidden"}), 403)
    return username, None


def _can_preview(username: str) -> bool:
    """Return whether the user may enqueue dry-run jobs."""
    try:
        from router.routes import _can_run_module_jobs

        if _can_run_module_jobs(username, MODULE_NAME):
            return True
    except Exception:
        pass
    return _has_right(username, "run_jobs") or _has_right(username, "manage")


def _can_apply(username: str) -> bool:
    """Return whether the user may enqueue confirmed live jobs."""
    return _has_right(username, "apply_changes") or _has_right(username, "manage")


def _workflow_from_request(*, allow_confirmation: bool = False) -> tuple[WorkflowSpec, dict]:
    """Parse the bounded legacy recipe invocation accepted by compatibility APIs."""
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
    """Create and dispatch a framework job for a legacy workflow recipe."""
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


def _enqueue_saltlick(
    saltlick_id: str,
    *,
    username: str,
    live: bool,
    inputs: dict,
    arguments: list[str],
    preview_token: str = "",
) -> int:
    """Create and dispatch a framework job for one compiled child Saltlick."""
    from module_tasks import process_module_job_run
    from router.module_registry import (
        ModuleJobConcurrencyError,
        create_module_job_run,
    )

    job_name = "apply" if live else "preview"
    payload = {
        "saltlick_id": saltlick_id,
        "inputs": inputs,
        "arguments": arguments,
        "confirm_live": bool(live),
    }
    if preview_token:
        payload["preview_token"] = preview_token
    try:
        run_id = create_module_job_run(
            MODULE_NAME,
            job_name,
            trigger_type="manual",
            triggered_by=username,
            payload=payload,
            concurrency_policy="forbid" if live else "allow",
        )
    except ModuleJobConcurrencyError as exc:
        raise ActiveRunError(exc.active_run_ids) from exc
    process_module_job_run.delay(run_id)
    return run_id


@blueprint.get("/auth")
def auth_api():
    """Return the signed-in user's Salt Shack capabilities."""
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


@blueprint.get("/saltlicks")
def saltlicks_api():
    """Return public contracts for every Saltlick compiled into the image."""
    _, denied = _require_access()
    if denied:
        return denied
    payload = registry_payload()
    payload["fingerprint"] = registry_fingerprint()
    return jsonify(payload)


@blueprint.get("/saltlicks/<saltlick_id>")
def saltlick_contract_api(saltlick_id: str):
    """Return one public Saltlick contract without exposing its handler path."""
    _, denied = _require_access()
    if denied:
        return denied
    definition = get_saltlick(saltlick_id)
    if definition is None:
        return jsonify({"detail": "Saltlick not found"}), 404
    return jsonify(definition.as_dict(public=True))


@blueprint.post("/saltlicks/<saltlick_id>/runs")
def saltlick_run_api(saltlick_id: str):
    """Validate inputs and enqueue a preview or confirmed apply run."""
    username, denied = _require_access()
    if denied:
        return denied
    definition = get_saltlick(saltlick_id)
    if definition is None:
        return jsonify({"detail": "Saltlick not found"}), 404
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"detail": "request body must be an object"}), 400
    allowed = {
        "mode",
        "inputs",
        "arguments",
        "confirm_live",
        "preview_token",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        return jsonify(
            {"detail": f"unsupported request field(s): {', '.join(unknown)}"}
        ), 400
    mode = str(payload.get("mode") or "preview").strip().lower()
    if mode not in {"preview", "apply"}:
        return jsonify({"detail": "mode must be preview or apply"}), 400
    live = mode == "apply"
    if live:
        if not _can_apply(username or ""):
            return jsonify(
                {"detail": "Forbidden: apply_changes right required"}
            ), 403
        if payload.get("confirm_live") is not True:
            return jsonify(
                {"detail": "Live run requires confirm_live=true"}
            ), 400
        preview_token = str(payload.get("preview_token") or "").strip()
        if not preview_token:
            return jsonify(
                {"detail": "Live run requires a preview_token"}
            ), 400
    else:
        if not _can_preview(username or ""):
            return jsonify({"detail": "Forbidden: run_jobs right required"}), 403
        preview_token = ""
    try:
        inputs = validate_inputs(definition.contract, payload.get("inputs"))
        arguments = validate_arguments(payload.get("arguments"))
        run_id = _enqueue_saltlick(
            definition.id,
            username=username or "",
            live=live,
            inputs=inputs,
            arguments=arguments,
            preview_token=preview_token,
        )
    except ActiveRunError as exc:
        return jsonify(
            {"detail": str(exc), "active_run_ids": exc.run_ids}
        ), 409
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400
    return jsonify(
        {
            "status": "queued",
            "run_id": run_id,
            "job": "apply" if live else "preview",
            "saltlick_id": definition.id,
            "contract": public_contract(definition.contract),
        }
    ), 202


@blueprint.get("/saltlicks/<saltlick_id>/runs")
def saltlick_runs_api(saltlick_id: str):
    """List recent runs visible to the current user for one Saltlick."""
    username, denied = _require_access()
    if denied:
        return denied
    definition = get_saltlick(saltlick_id)
    if definition is None:
        return jsonify({"detail": "Saltlick not found"}), 404
    from router.module_registry import list_module_job_runs

    can_manage = _has_right(username or "", "manage")
    runs = []
    for run in list_module_job_runs(MODULE_NAME, limit=100):
        payload = run.get("payload") or {}
        if payload.get("saltlick_id") != definition.id:
            continue
        owner = str(run.get("triggered_by") or "")
        if owner and owner != username and not can_manage:
            continue
        runs.append(
            {
                "id": run["id"],
                "job_name": run.get("job_name"),
                "status": run.get("status"),
                "triggered_by": run.get("triggered_by"),
                "created_at": run.get("created_at"),
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "error": run.get("error"),
                "result": run.get("result") or {},
            }
        )
        if len(runs) >= 25:
            break
    return jsonify({"saltlick_id": definition.id, "runs": runs})


@blueprint.post("/validate")
def validate_api():
    """Validate a legacy workflow recipe and return generated fork sources."""
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
    """Queue a dry run for the legacy workflow-recipe compatibility API."""
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
    """Queue a confirmed live run for the legacy compatibility API."""
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
    """Return one owned Salt Shack run for UI polling."""
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
