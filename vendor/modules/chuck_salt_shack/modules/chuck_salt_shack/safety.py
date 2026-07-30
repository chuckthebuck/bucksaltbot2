"""Per-Saltlick grants and persistent emergency-stop state."""

from __future__ import annotations

from typing import Any


MODULE_NAME = "chuck_salt_shack"
_ESTOP_CONFIG_KEY = "saltlick_estops"
_ACTIVE_RUN_STATUSES = {"queued", "launching", "running", "cancel_requested"}


def saltlick_right(saltlick_id: str, capability: str) -> str:
    """Return the generated module-right suffix for one immutable Saltlick."""
    saltlick_id = str(saltlick_id or "").strip().lower().replace("-", "_")
    capability = str(capability or "").strip().lower().replace("-", "_")
    if not saltlick_id or capability not in {"preview", "apply", "estop"}:
        raise ValueError("invalid Saltlick right")
    return f"saltlick_{saltlick_id}_{capability}"


def saltlick_rights(saltlick_id: str) -> dict[str, str]:
    """Return every independently grantable right generated for a Saltlick."""
    return {
        capability: saltlick_right(saltlick_id, capability)
        for capability in ("preview", "apply", "estop")
    }


def _disabled_saltlicks() -> set[str]:
    """Read persistent stopped Saltlick IDs from framework module config."""
    from router.module_registry import get_module_config

    try:
        raw = get_module_config(MODULE_NAME).get(_ESTOP_CONFIG_KEY, [])
    except Exception:
        # Local contract/UI tooling runs without ToolsDB; an unavailable
        # persistence layer must not make every Saltlick appear stopped.
        raw = []
    return {
        str(item).strip().lower().replace("-", "_")
        for item in raw
        if str(item).strip()
    } if isinstance(raw, list) else set()


def saltlick_is_enabled(saltlick_id: str) -> bool:
    """Return whether this Saltlick has not been independently emergency-stopped."""
    normalized = str(saltlick_id or "").strip().lower().replace("-", "_")
    return normalized not in _disabled_saltlicks()


def set_saltlick_enabled(
    saltlick_id: str,
    enabled: bool,
    *,
    actor: str | None = None,
) -> None:
    """Persist an individual Saltlick stop/resume state."""
    from router.module_registry import upsert_module_config

    normalized = str(saltlick_id or "").strip().lower().replace("-", "_")
    if not normalized:
        raise ValueError("saltlick_id is required")
    disabled = _disabled_saltlicks()
    if enabled:
        disabled.discard(normalized)
    else:
        disabled.add(normalized)
    upsert_module_config(
        MODULE_NAME,
        {_ESTOP_CONFIG_KEY: sorted(disabled)},
        updated_by=actor,
    )


def emergency_stop_saltlick(
    saltlick_id: str,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    """Stop one Saltlick and cancel only its active persisted module runs."""
    from router.module_registry import list_module_job_runs, request_module_job_run_cancel

    set_saltlick_enabled(saltlick_id, False, actor=actor)
    canceled = []
    for run in list_module_job_runs(MODULE_NAME, limit=1000):
        if (
            run.get("status") in _ACTIVE_RUN_STATUSES
            and (run.get("payload") or {}).get("saltlick_id") == saltlick_id
        ):
            request_module_job_run_cancel(int(run["id"]))
            canceled.append(int(run["id"]))
    return {"saltlick_id": saltlick_id, "enabled": False, "canceled_runs": canceled}
