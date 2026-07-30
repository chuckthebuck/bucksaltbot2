"""Pywikibot page-source adapters for Saltlick."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import islice
from typing import Any

from .spec import SourceSpec


def resolve_pages(
    site: Any,
    source: SourceSpec,
    *,
    pywikibot_module: Any | None = None,
) -> Iterable[Any]:
    """Build a bounded Pywikibot page iterator from a source specification."""
    if pywikibot_module is None:
        import pywikibot as pywikibot_module
    from pywikibot import pagegenerators

    namespaces = list(source.namespaces) or None
    if source.type == "titles":
        pages = (
            pywikibot_module.Page(site, title)
            for title in source.titles
        )
    elif source.type == "category":
        category_title = source.target
        if not category_title.lower().startswith("category:"):
            category_title = f"Category:{category_title}"
        category = pywikibot_module.Category(site, category_title)
        pages = category.articles(
            recurse=source.recursive,
            total=source.limit,
            namespaces=namespaces,
        )
    elif source.type == "backlinks":
        page = pywikibot_module.Page(site, source.target)
        pages = page.getReferences(
            follow_redirects=True,
            only_template_inclusion=source.only_template_inclusion,
            namespaces=namespaces,
            total=source.limit,
            content=False,
        )
    elif source.type == "links":
        page = pywikibot_module.Page(site, source.target)
        pages = pagegenerators.LinkedPageGenerator(page, total=source.limit)
    elif source.type == "search":
        pages = pagegenerators.SearchPageGenerator(
            source.target,
            total=source.limit,
            namespaces=namespaces,
            site=site,
        )
    elif source.type == "user_contribs":
        pages = pagegenerators.UserContributionsGenerator(
            source.target,
            namespaces=namespaces,
            site=site,
            total=source.limit,
        )
    elif source.type == "recent_changes":
        changes = site.recentchanges(
            namespaces=namespaces,
            total=source.limit,
        )
        pages = (
            pywikibot_module.Page(site, str(change.get("title") or ""))
            for change in changes
            if change.get("title")
        )
    elif source.type == "prefix":
        pages = site.allpages(
            prefix=source.target,
            namespace=source.namespaces[0] if source.namespaces else 0,
            total=source.limit,
            content=False,
        )
    else:  # pragma: no cover - SourceSpec rejects this
        raise ValueError(f"unsupported source type: {source.type}")
    return islice(pages, source.limit)
