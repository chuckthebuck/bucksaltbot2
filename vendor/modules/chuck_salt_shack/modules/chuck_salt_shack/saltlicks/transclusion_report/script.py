"""Produce a bounded transclusion report without planning any wiki writes.

This is the reference read-only Saltlick: it may use the authenticated
framework context to query Pywikibot, but its contract declares an empty action
allowlist and its result always contains an empty action plan.
"""

from __future__ import annotations

from typing import Any


def run(ctx: Any, inputs: dict, arguments: list[str]) -> dict:
    """Collect and normalize template references for the shared table renderer.

    All values in ``inputs`` are contract-validated before this function is
    loaded.  Raw compatibility arguments are unused because the typed contract
    is the complete public interface for this Saltlick.
    """
    del arguments
    wiki = inputs["wiki"]

    # Site construction stays behind the run context so the framework owns
    # Pywikibot environment setup, login, and cancellation policy.
    site = ctx.site(wiki["code"], wiki["family"])
    template_input = inputs["template"]

    import pywikibot

    template = pywikibot.Page(
        site,
        template_input["title"],
        ns=template_input["namespace"],
    )

    # ``template.namespace`` identifies the source template; ``namespace``
    # filters the pages returned by getReferences.  They are intentionally
    # separate contract fields.
    pages = template.getReferences(
        only_template_inclusion=True,
        namespaces=[inputs["namespace"]],
        follow_redirects=bool(inputs["include_redirects"]),
        total=inputs["limit"],
    )
    matches = []
    for page in pages:
        # A reference query can be large even with a total limit, so preserve a
        # cancellation boundary for every page materialized into the report.
        ctx.check_cancelled()
        namespace = int(page.namespace())
        matches.append(
            {
                "page": {
                    "wiki": wiki,
                    "namespace": namespace,
                    "title": str(page.title()),
                },
                "namespace": namespace,
                "redirect": bool(page.isRedirectPage()),
            }
        )

    # The table rows use only JSON-safe primitives and typed page objects.
    # Salt Shack validates every required column before persisting the run.
    return {
        "outputs": {
            "count": len(matches),
            "matches": matches,
        },
        "actions": [],
    }
