"""Plan cache purges without giving this Saltlick direct write authority.

The script translates contract-normalized inputs into declarative action
envelopes.  Salt Shack validates those envelopes and the framework's reviewed
action catalog performs them only during a confirmed apply run.
"""

from __future__ import annotations

from typing import Any


def run(ctx: Any, inputs: dict, arguments: list[str]) -> dict:
    """Return structured preview output and one purge action per target.

    ``inputs`` has already passed the installed ``saltlick.yaml`` contract.
    The compatibility arguments are deliberately ignored because this
    Saltlick exposes every supported purge option as a typed field.
    """
    del ctx, arguments
    wiki = inputs["wiki"]

    # Page inputs carry title and namespace.  Attach the separately selected
    # wiki here so every action target is self-contained when the framework
    # groups a mixed action plan by site.
    targets = [
        {
            **target,
            "wiki": wiki,
        }
        for target in inputs["targets"]
    ]

    # Saltlick code describes intent only.  In preview mode these envelopes
    # are rendered as the reviewable plan; in apply mode the framework checks
    # the preview digest before dispatching this allowlisted action type.
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

    # Outputs are presentation data, while actions are executable intent.
    # Keeping both explicit lets the output contract and action allowlist be
    # validated independently at the trust boundary.
    return {
        "outputs": {
            "planned_count": len(actions),
            "targets": targets,
        },
        "actions": actions,
    }
