"""Small Pywikibot adapter for Commons file-page reads and writes."""

from __future__ import annotations

from dataclasses import dataclass

import pywikibot

from .config import COMMONS_SITE_CODE, COMMONS_SITE_FAMILY, user_agent


@dataclass
class WikiClient:
    """Own one configured Pywikibot site and enforce dry-run writes locally."""
    dry_run: bool = True
    site_code: str = COMMONS_SITE_CODE
    site_family: str = COMMONS_SITE_FAMILY
    user_agent_value: str = ""

    def __post_init__(self) -> None:
        """Apply the identifying User-Agent before constructing the site."""
        # Pywikibot reads this global format while building requests, so set it
        # before Site construction. The service fixes coordinates to Commons.
        pywikibot.config.user_agent_format = self.user_agent_value or user_agent()
        self.site = pywikibot.Site(self.site_code, self.site_family)

    def get_text(self, title: str) -> str:
        """Load current wikitext for one normalized file-page title."""
        page = pywikibot.Page(self.site, title)
        return page.text

    def save_text(self, title: str, text: str, summary: str) -> None:
        """Save bot-marked text unless this client is in dry-run mode."""
        # The service already separates preview from apply, but this adapter-
        # level guard prevents an accidental direct save through a preview client.
        if self.dry_run:
            return
        page = pywikibot.Page(self.site, title)
        page.text = text
        page.save(summary=summary, minor=False, bot=True)
