"""Compatibility helpers for logged, environment-gated Pywikibot edits."""

import pywikibot as pwb
import os
from logger import Logger
from editsummary import editsummaries


def safe_put(page: pwb.Page, text: str, summary: str, logger: Logger):
    """Log a proposed edit and save it only in configured production mode."""
    if page.site.code in editsummaries:
        summary_ext = editsummaries[page.site.code]
    else:
        summary_ext = editsummaries["default"]
    summary = summary + " " + summary_ext
    logger.log("TITLE:" + page.title())
    logger.log("TEXT:" + text)
    logger.log("SUMMARY:" + summary)
    # Local runs remain preview-only even when callers forget to request dry-run.
    if os.environ.get("NOTDEV"):
        page.text = text
        page.save(summary=str(summary), bot=True)
