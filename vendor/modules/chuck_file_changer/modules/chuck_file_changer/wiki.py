from __future__ import annotations

from dataclasses import dataclass

import pywikibot

from .config import COMMONS_SITE_CODE, COMMONS_SITE_FAMILY, user_agent


@dataclass
class WikiClient:
    dry_run: bool = True
    site_code: str = COMMONS_SITE_CODE
    site_family: str = COMMONS_SITE_FAMILY
    user_agent_value: str = ""

    def __post_init__(self) -> None:
        pywikibot.config.user_agent_format = self.user_agent_value or user_agent()
        self.site = pywikibot.Site(self.site_code, self.site_family)

    def get_text(self, title: str) -> str:
        page = pywikibot.Page(self.site, title)
        return page.text

    def save_text(self, title: str, text: str, summary: str) -> None:
        if self.dry_run:
            return
        page = pywikibot.Page(self.site, title)
        page.text = text
        page.save(summary=summary, minor=False)
