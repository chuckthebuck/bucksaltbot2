"""Generate per-child rights and persist independent emergency-stop state.

The framework already owns a Shack-wide emergency stop.  This layer adds a
narrower switch so operators can suspend one compiled Saltlick, cancel only
its active runs, and leave unrelated children available.
"""

from __future__ import annotations

from typing import Any


MODULE_NAME = "chuck_salt_shack"
_ESTOP_CONFIG_KEY = "saltlick_estops"
_ACTIVE_RUN_STATUSES = {"queued", "launching", "running", "cancel_requested"}


def saltlick_right(saltlick_id: str, capability: str) -> str:
    """Return the stable module-right suffix for one child capability.

    This returns a suffix such as ``saltlick_page_purger_apply``; framework
    authorization adds the module namespace when storing/checking grants.
    """
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
    """Read normalized stopped IDs from framework-owned module config.

    Local registry/build tooling may import this module without ToolsDB, so an
    unavailable config store degrades to no child-specific stops.  The separate
    framework-wide emergency stop and authorization checks are not represented
    by this set.
    """
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
    """Return whether the normalized child ID is absent from the stop set."""
    normalized = str(saltlick_id or "").strip().lower().replace("-", "_")
    return normalized not in _disabled_saltlicks()


def set_saltlick_enabled(
    saltlick_id: str,
    enabled: bool,
    *,
    actor: str | None = None,
) -> None:
    """Persist an individual child stop/resume state as a sorted ID list.

    Sorting makes configuration updates deterministic for audits and avoids
    tying persistence to Python set iteration order.
    """
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
    """Stop one child, then request cancellation for its active run rows.

    Disabling is persisted first, so a worker that has not passed its enabled
    check rejects the run. Cancellation of an already active worker remains a
    best-effort framework request. Completed/failed rows stay in history.
    """
    from router.module_registry import list_module_job_runs, request_module_job_run_cancel

    set_saltlick_enabled(saltlick_id, False, actor=actor)
    canceled = []
    for run in list_module_job_runs(MODULE_NAME, limit=1000):
        # Payload ownership is the child boundary because all Saltlicks share
        # the same framework module job table and worker definitions.
        if (
            run.get("status") in _ACTIVE_RUN_STATUSES
            and (run.get("payload") or {}).get("saltlick_id") == saltlick_id
        ):
            request_module_job_run_cancel(int(run["id"]))
            canceled.append(int(run["id"]))
    return {"saltlick_id": saltlick_id, "enabled": False, "canceled_runs": canceled}
