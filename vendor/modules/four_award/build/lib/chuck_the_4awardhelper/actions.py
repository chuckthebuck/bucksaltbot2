from __future__ import annotations

import re

from .config import ENABLE_ARTICLE_HISTORY, ENABLE_REMOVAL, FOUR_PAGE
from .models import FourAwardNomination
from .wiki import get_wiki


def remove_nomination(nomination: FourAwardNomination) -> bool:
    if not ENABLE_REMOVAL:
        return False
    wiki = get_wiki()
    text = wiki.get_text(FOUR_PAGE)
    new_text = text.replace(nomination.raw_text, "", 1)
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    if new_text == text:
        return False
    wiki.save_text(FOUR_PAGE, new_text, f"Remove reviewed Four Award nomination for [[{nomination.article}]]")
    return True


def set_article_history_four(article: str, value: str) -> bool:
    if not ENABLE_ARTICLE_HISTORY:
        return False
    wiki = get_wiki()
    title = f"Talk:{article}"
    text = wiki.get_text(title)
    match = re.search(r"\{\{\s*Article history\b.*?\n\}\}", text, re.I | re.S)
    if not match:
        match = re.search(r"\{\{\s*Article history\b.*?\}\}", text, re.I | re.S)
    if not match:
        return False
    template = match.group(0)
    if re.search(r"\|\s*four\s*=", template, re.I):
        new_template = re.sub(r"(\|\s*four\s*=\s*)[^\n|}]+", rf"\g<1>{value}", template, count=1, flags=re.I)
    else:
        insert_at = template.rfind("}}")
        new_template = f"{template[:insert_at]}|four={value}\n{template[insert_at:]}"
    wiki.save_text(title, text[: match.start()] + new_template + text[match.end() :], f"Mark [[{article}]] Four Award review result")
    return True
