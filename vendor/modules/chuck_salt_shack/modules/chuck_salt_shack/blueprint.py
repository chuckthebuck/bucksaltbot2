"""Expose authenticated HTTP APIs without exposing Saltlick code locations.

The blueprint is the browser-facing validation and authorization layer.  It
returns public contracts, applies Shack-wide or per-Saltlick rights, persists
jobs through the framework registry, and leaves execution-time revalidation to
the worker service.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from .codegen import render_jobs_py, render_module_toml
from .contracts import public_contract, validate_arguments, validate_inputs
from .registry import (
    discover_saltlicks,
    get_saltlick,
    registry_fingerprint,
    registry_payload,
)
from .safety import (
    emergency_stop_saltlick,
    saltlick_is_enabled,
    saltlick_right,
    set_saltlick_enabled,
)
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
    """Query one module-scoped right and fail closed on auth backend errors."""
    try:
        from router.authz import user_has_module_right

        return user_has_module_right(username, MODULE_NAME, right)
    except Exception:
        return False


def _has_access(username: str) -> bool:
    """Return whether any Shack-wide or generated child grant allows entry.

    A user with only one per-Saltlick right must be able to load the catalog in
    order to reach that child, even without a broad module access grant.
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
    # Compatibility installations may grant the older Shack-wide rights, while
    # newer deployments can grant one generated capability per child.
    return (
        any(
            _has_right(username, right)
            for right in ("manage", "run_jobs", "apply_changes")
        )
        or any(
            _has_right(username, saltlick_right(definition.id, capability))
            for definition in discover_saltlicks()
            for capability in ("preview", "apply", "estop")
        )
    )


def _require_access():
    """Return the username or a ready 401/403 response for route reuse."""
    username = _username()
    if not username:
        return None, (jsonify({"detail": "Not authenticated"}), 401)
    if not _has_access(username):
        return None, (jsonify({"detail": "Forbidden"}), 403)
    return username, None


def _can_preview(username: str) -> bool:
    """Return whether broad framework/module policy permits dry-run jobs."""
    try:
        from router.routes import _can_run_module_jobs

        if _can_run_module_jobs(username, MODULE_NAME):
            return True
    except Exception:
        pass
    return _has_right(username, "run_jobs") or _has_right(username, "manage")


def _can_apply(username: str) -> bool:
    """Require a configured Shack/global grant for confirmed live jobs.

    This raw module-right path does not inherit framework maintainer status;
    maintainers need ``manage_modules`` or an explicit Shack apply/manage grant.
    """
    return _has_right(username, "apply_changes") or _has_right(username, "manage")


def _can_saltlick_preview(username: str, saltlick_id: str) -> bool:
    """Combine broad Shack permission with one generated preview grant."""
    return _can_preview(username) or _has_right(username, saltlick_right(saltlick_id, "preview"))


def _can_saltlick_apply(username: str, saltlick_id: str) -> bool:
    """Allow the legacy Shack grant or the generated Saltlick apply grant."""
    return _can_apply(username) or _has_right(username, saltlick_right(saltlick_id, "apply"))


def _can_estop_saltlick(username: str, saltlick_id: str) -> bool:
    """Allow configured Shack/global or Saltlick-specific stop authority.

    Framework maintainer status alone is not added by this custom-route helper.
    """
    return (
        _has_right(username, "manage")
        or _has_right(username, "estop")
        or _has_right(username, saltlick_right(saltlick_id, "estop"))
    )


def _workflow_from_request(*, allow_confirmation: bool = False) -> tuple[WorkflowSpec, dict]:
    """Parse the closed legacy recipe shape accepted by compatibility APIs.

    The compatibility surface accepts data-driven recipes only.  Rejecting
    unknown top-level fields prevents it from becoming a handler/source upload
    route as the main UI evolves.
    """
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
    """Persist then dispatch one validated legacy workflow invocation."""
    from module_tasks import process_module_job_run
    from router.module_registry import (
        ModuleJobConcurrencyError,
        create_module_job_run,
    )

    # Persist before dispatch so the worker always has an auditable run row.
    # Live compatibility runs are serialized; previews are safe to overlap.
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
    """Persist then dispatch one normalized compiled-child invocation.

    Only the stable child ID, normalized values, and reviewed token are queued;
    entrypoint paths remain in the installed registry.
    """
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
        # Preview runs never need a caller-supplied token.  Apply runs preserve
        # it for worker-side comparison after regenerating the action plan.
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
    """Return broad and per-child capabilities for client-side affordances.

    These flags control what the UI offers; every mutating route still performs
    its own authorization check and the worker still enforces run safety.
    """
    username, denied = _require_access()
    if denied:
        return denied
    saltlick_capabilities = {
        definition.id: {
            "can_preview": _can_saltlick_preview(username or "", definition.id),
            "can_apply": _can_saltlick_apply(username or "", definition.id),
            "can_estop": _can_estop_saltlick(username or "", definition.id),
            "enabled": saltlick_is_enabled(definition.id),
        }
        for definition in discover_saltlicks()
    }
    return jsonify(
        {
            "username": username,
            "can_preview": _can_preview(username or ""),
            "can_apply": _can_apply(username or ""),
            "can_manage": _has_right(username or "", "manage"),
            "can_estop": _has_right(username or "", "estop")
            or _has_right(username or "", "manage"),
            "saltlicks": saltlick_capabilities,
        }
    )


@blueprint.get("/saltlicks")
def saltlicks_api():
    """Return public contracts and a deterministic catalog fingerprint."""
    _, denied = _require_access()
    if denied:
        return denied
    payload = registry_payload()
    payload["fingerprint"] = registry_fingerprint()
    return jsonify(payload)


@blueprint.get("/saltlicks/<saltlick_id>")
def saltlick_contract_api(saltlick_id: str):
    """Return one public contract without exposing its fixed handler path."""
    _, denied = _require_access()
    if denied:
        return denied
    definition = get_saltlick(saltlick_id)
    if definition is None:
        return jsonify({"detail": "Saltlick not found"}), 404
    return jsonify(definition.as_dict(public=True))


@blueprint.post("/saltlicks/<saltlick_id>/runs")
def saltlick_run_api(saltlick_id: str):
    """Authorize, normalize, and enqueue a preview or confirmed apply run.

    Validation here gives immediate HTTP feedback.  The worker deliberately
    repeats it because persisted queue payloads are a separate trust boundary.
    """
    username, denied = _require_access()
    if denied:
        return denied
    definition = get_saltlick(saltlick_id)
    if definition is None:
        return jsonify({"detail": "Saltlick not found"}), 404
    if not saltlick_is_enabled(definition.id):
        return jsonify({"detail": "Saltlick is emergency-stopped"}), 409
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
    # Preview is the safe default.  Live intent must be stated consistently by
    # mode, permission, confirmation flag, and a non-empty preview token.
    mode = str(payload.get("mode") or "preview").strip().lower()
    if mode not in {"preview", "apply"}:
        return jsonify({"detail": "mode must be preview or apply"}), 400
    live = mode == "apply"
    if live:
        if not _can_saltlick_apply(username or "", definition.id):
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
        if not _can_saltlick_preview(username or "", definition.id):
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


@blueprint.post("/saltlicks/<saltlick_id>/estop")
def saltlick_estop_api(saltlick_id: str):
    """Independently stop/resume a child and cancel its active runs on stop."""
    username, denied = _require_access()
    if denied:
        return denied
    definition = get_saltlick(saltlick_id)
    if definition is None:
        return jsonify({"detail": "Saltlick not found"}), 404
    if not _can_estop_saltlick(username or "", definition.id):
        return jsonify({"detail": "Forbidden: Saltlick estop right required"}), 403
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict) or set(payload) - {"enabled"}:
        return jsonify({"detail": "request body may only contain enabled"}), 400
    enabled = bool(payload.get("enabled", False))
    if enabled:
        set_saltlick_enabled(definition.id, True, actor=username)
        return jsonify({"saltlick_id": definition.id, "enabled": True, "canceled_runs": []})
    return jsonify(emergency_stop_saltlick(definition.id, actor=username))


@blueprint.get("/saltlicks/<saltlick_id>/runs")
def saltlick_runs_api(saltlick_id: str):
    """List recent owned child runs, or all child runs for a module manager."""
    username, denied = _require_access()
    if denied:
        return denied
    definition = get_saltlick(saltlick_id)
    if definition is None:
        return jsonify({"detail": "Saltlick not found"}), 404
    from router.module_registry import list_module_job_runs

    can_manage = _has_right(username or "", "manage")
    runs = []
    # Filter persisted module runs in-process because the framework store is
    # module-scoped, while this endpoint is deliberately child-scoped.
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
    """Validate a legacy recipe and return deterministic fork-ready sources."""
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
    """Queue a dry run for the non-UI legacy recipe compatibility API."""
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
    """Queue a confirmed live run for the non-UI legacy compatibility API."""
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
    """Return one module-owned run for polling, subject to row ownership."""
    username, denied = _require_access()
    if denied:
        return denied
    from router.module_registry import get_module_job_run

    run = get_module_job_run(run_id)
    # Return the same 404 for absent and cross-module IDs so this module cannot
    # be used to enumerate another module's job records.
    if run is None or run.get("module_name") != MODULE_NAME:
        return jsonify({"detail": "Run not found"}), 404
    owner = str(run.get("triggered_by") or "")
    if owner and owner != username and not _has_right(username or "", "manage"):
        return jsonify({"detail": "Forbidden"}), 403
    return jsonify(run)
