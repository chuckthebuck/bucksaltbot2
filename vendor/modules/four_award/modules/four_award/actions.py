"""Apply post-review changes to nominations and article talk pages.

Feature flags decide whether each action is attempted.  The shared wiki client
then decides whether a proposed save is recorded as a dry-run diff or published
live, so these helpers use the same text-transformation path in both modes.
"""

from __future__ import annotations

import re

from .config import ENABLE_ARTICLE_HISTORY, ENABLE_REMOVAL, FOUR_PAGE
from .models import FourAwardNomination
from .wiki import get_wiki


def remove_nomination(nomination: FourAwardNomination) -> bool:
    """Remove the first exact copy of a reviewed nomination block.

    Return ``False`` when removal is disabled or the parser's captured block is
    no longer present.  ``True`` means a changed page was handed to ``save_text``;
    in dry-run mode that save is recorded as a proposal rather than published.
    """
    if not ENABLE_REMOVAL:
        return False
    wiki = get_wiki()
    text = wiki.get_text(FOUR_PAGE)
    # The parser retains the complete heading block specifically so removal can
    # avoid a broad regex that might consume an adjacent nomination.
    new_text = text.replace(nomination.raw_text, "", 1)
    # Removing a block can join surrounding blank lines; keep normal wiki spacing.
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    if new_text == text:
        return False
    wiki.save_text(FOUR_PAGE, new_text, f"Remove reviewed Four Award nomination for [[{nomination.article}]]")
    return True


def set_article_history_four(article: str, value: str) -> bool:
    """Set or append ``four=`` on the article talk page's history template.

    Multiline and compact one-line ``Article history`` forms are supported.  The
    function returns ``False`` when disabled or when no template can be located;
    otherwise the wiki adapter handles dry-run versus live publication.
    """
    if not ENABLE_ARTICLE_HISTORY:
        return False
    wiki = get_wiki()
    title = f"Talk:{article}"
    text = wiki.get_text(title)
    # Prefer the multiline boundary because it is less likely to stop at braces
    # belonging to a nested template.  The compact form is a legacy fallback.
    match = re.search(r"\{\{\s*Article history\b.*?\n\}\}", text, re.I | re.S)
    if not match:
        match = re.search(r"\{\{\s*Article history\b.*?\}\}", text, re.I | re.S)
    if not match:
        return False
    template = match.group(0)
    if re.search(r"\|\s*four\s*=", template, re.I):
        # Replace only the first scalar value; other history fields are preserved.
        new_template = re.sub(r"(\|\s*four\s*=\s*)[^\n|}]+", rf"\g<1>{value}", template, count=1, flags=re.I)
    else:
        # Append near the closing braces to avoid disturbing existing history fields.
        insert_at = template.rfind("}}")
        new_template = f"{template[:insert_at]}|four={value}\n{template[insert_at:]}"
    wiki.save_text(title, text[: match.start()] + new_template + text[match.end() :], f"Mark [[{article}]] Four Award review result")
    return True
