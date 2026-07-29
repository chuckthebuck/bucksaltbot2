"""Pywikibot job handlers for the template module."""

from __future__ import annotations


def run(ctx, payload):
    """Run reviewed module code inside the framework's isolated job process.

    Replace the body with the custom Pywikibot workflow. The framework supplies
    configuration, logging, cancellation, OAuth setup, and run tracking.
    """
    ctx.check_cancelled()
    ctx.logger.log(f"Starting {ctx.module_name}/{ctx.job_name}")

    # A logged-in site is one line when the script needs it:
    #
    # site = ctx.site(
    #     str(payload.get("code") or "commons"),
    #     str(payload.get("family") or "commons"),
    # )
    # import pywikibot
    # page = pywikibot.Page(site, "File:Example.jpg")

    return {
        "ok": True,
        "dry_run": bool(ctx.config.get("dry_run", True)),
        "payload": payload,
    }
