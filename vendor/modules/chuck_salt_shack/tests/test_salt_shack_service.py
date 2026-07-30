import pytest

from chuck_salt_shack.service import execute_saltlick


class FakeContext:
    def __init__(self, job_name="preview"):
        self.job_name = job_name
        self.config = {}
        self.executions = []

    def execute_actions(self, actions, *, dry_run, allowed_types):
        self.executions.append(
            {
                "actions": actions,
                "dry_run": dry_run,
                "allowed_types": tuple(allowed_types),
            }
        )
        return {
            "ok": True,
            "dry_run": dry_run,
            "planned_count": len(actions),
            "completed_count": 0 if dry_run else len(actions),
            "error_count": 0,
            "items": [
                {
                    "index": index,
                    **action,
                    "status": "planned" if dry_run else "completed",
                }
                for index, action in enumerate(actions)
            ],
        }


def purge_payload():
    return {
        "saltlick_id": "page_purger",
        "inputs": {
            "targets": [
                {"title": "Main Page", "namespace": 0},
                {"title": "Example", "namespace": 10},
            ],
        },
        "arguments": ["-verbose"],
    }


def test_preview_dispatches_fixed_image_entrypoint_and_returns_plan_digest():
    ctx = FakeContext("preview")

    result = execute_saltlick(ctx, purge_payload())

    assert result["saltlick"]["id"] == "page_purger"
    assert result["dry_run"] is True
    assert result["outputs"]["planned_count"] == 2
    assert len(result["plan_token"]) == 64
    assert ctx.executions[0]["dry_run"] is True
    assert ctx.executions[0]["allowed_types"] == ("mediawiki.page.purge",)


def test_apply_requires_the_exact_previewed_plan():
    preview = execute_saltlick(FakeContext("preview"), purge_payload())
    apply_payload = {
        **purge_payload(),
        "confirm_live": True,
        "preview_token": preview["plan_token"],
    }
    apply_ctx = FakeContext("apply")

    result = execute_saltlick(apply_ctx, apply_payload)

    assert result["dry_run"] is False
    assert apply_ctx.executions[0]["dry_run"] is False

    changed = {
        **apply_payload,
        "inputs": {
            "targets": [{"title": "Different", "namespace": 0}],
        },
    }
    with pytest.raises(ValueError, match="plan changed"):
        execute_saltlick(FakeContext("apply"), changed)


def test_endpoint_payload_cannot_select_a_script_path():
    payload = {
        **purge_payload(),
        "script": "../../other.py",
    }
    with pytest.raises(ValueError, match="unsupported run argument"):
        execute_saltlick(FakeContext("preview"), payload)
