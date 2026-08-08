"""Find pages transcluding a template without modifying the wiki."""

from __future__ import annotations

from typing import Any


def run(ctx: Any, inputs: dict, arguments: list[str]) -> dict:
    """Collect a bounded, read-only report of template transclusions."""
    del arguments
    wiki = inputs["wiki"]
    site = ctx.site(wiki["code"], wiki["family"])
    template_input = inputs["template"]

    import pywikibot

    template = pywikibot.Page(
        site,
        template_input["title"],
        ns=template_input["namespace"],
    )
    pages = template.getReferences(
        only_template_inclusion=True,
        namespaces=[inputs["namespace"]],
        follow_redirects=bool(inputs["include_redirects"]),
        total=inputs["limit"],
    )
    matches = []
    for page in pages:
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
    return {
        "outputs": {
            "count": len(matches),
            "matches": matches,
        },
        "actions": [],
    }
