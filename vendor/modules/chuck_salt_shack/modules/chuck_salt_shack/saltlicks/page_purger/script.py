"""Build a framework-owned purge action for each requested page."""

from __future__ import annotations

from typing import Any


def run(ctx: Any, inputs: dict, arguments: list[str]) -> dict:
    """Translate selected pages into framework-owned cache-purge actions."""
    del ctx, arguments
    wiki = inputs["wiki"]
    targets = [
        {
            **target,
            "wiki": wiki,
        }
        for target in inputs["targets"]
    ]
    actions = [
        {
            "type": "mediawiki.page.purge",
            "target": target,
            "params": {
                "forcelinkupdate": bool(inputs["force_link_update"]),
                "forcerecursivelinkupdate": bool(
                    inputs["recursive_link_update"]
                ),
            },
        }
        for target in targets
    ]
    return {
        "outputs": {
            "planned_count": len(actions),
            "targets": targets,
        },
        "actions": actions,
    }
