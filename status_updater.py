"""Chuckbot on-wiki status page updates and talk-page notification helpers.

All functions that perform wiki edits are gated behind the ``NOTDEV``
environment variable (the same convention used elsewhere in this codebase).
When ``NOTDEV`` is unset the functions return immediately so that tests and
development environments never accidentally touch the live wiki.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pywikibot

from redis_state import r as _redis

# ── Page titles ───────────────────────────────────────────────────────────────

STATUS_PAGE = "User:Alachuckthebuck/chuckbot/status"
NOTIFY_PAGE = "User:Alachuckthebuck/chuckbot/notify"

# ── Redis key settings ────────────────────────────────────────────────────────

_NOTIFIED_BATCH_TTL = 7 * 24 * 3600  # 7 days


# ── Internal helpers ──────────────────────────────────────────────────────────


def _is_live() -> bool:
    """Return True when running in production (``NOTDEV`` is set)."""
    return bool(os.environ.get("NOTDEV"))


# ── Public API ────────────────────────────────────────────────────────────────


def is_large_job(job_count: int) -> bool:
    """Return True when a batch spans more than one Celery job chunk."""
    return job_count > 1


def is_batch_already_notified(batch_id: int) -> bool:
    """Return True if maintainers have already been notified for *batch_id*."""
    try:
        return bool(_redis.exists(f"rollback:notified_batch:{batch_id}"))
    except Exception:  # noqa: BLE001
        return False


def mark_batch_notified(batch_id: int) -> None:
    """Record in Redis that maintainers have been notified for *batch_id*."""
    try:
        _redis.set(
            f"rollback:notified_batch:{batch_id}",
            "1",
            ex=_NOTIFIED_BATCH_TTL,
        )
    except Exception:  # noqa: BLE001
        pass


def get_notify_list(site: pywikibot.Site) -> list[str]:
    """Read the list of users to notify from ``NOTIFY_PAGE`` on the wiki.

    The page is expected to contain ``[[User:Username]]`` wikilinks, one per
    line.  Returns an empty list on any error.
    """
    try:
        page = pywikibot.Page(site, NOTIFY_PAGE)
        users: list[str] = []
        for line in page.text.splitlines():
            if "[[User:" in line:
                start = line.find("[[User:") + 7
                end = line.find("]]", start)
                if end > start:
                    users.append(line[start:end])
        return users
    except Exception:  # noqa: BLE001
        return []


def is_flagged_bot(site: pywikibot.Site, username: str) -> bool:
    """Return True if *username* has the ``bot`` user group on *site*."""
    try:
        return "bot" in pywikibot.User(site, username).groups()
    except Exception:  # noqa: BLE001
        return False


def update_wiki_status(
    editing: str,
    web: str = "🟢 Online",
    *,
    last_edit: str | None = None,
    current_job: str | None = None,
    last_job: str | None = None,
    details: str = "",
    warning: str | None = None,
) -> None:
    """Rewrite the on-wiki Chuckbot status page.  No-op in dev / test mode."""
    if not _is_live():
        return

    try:
        site = pywikibot.Site("commons", "commons")
        page = pywikibot.Page(site, STATUS_PAGE)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        lines = [
            "{{Chuckbot status",
            f"| editing = {editing}",
            f"| web = {web}",
            f"| last_edit = {last_edit or 'Unknown'}",
            f"| current_job = {current_job or 'None'}",
            f"| last_job = {last_job or 'None'}",
            f"| details = {details}",
        ]
        if warning:
            lines.append(f"| warning = {warning}")
        lines.append(f"| updated = {now}")
        lines.append("}}")

        page.text = "\n".join(lines)
        page.save(summary="Updating Chuckbot status", minor=True, botflag=True)
    except Exception:  # noqa: BLE001
        pass


def notify_maintainers(
    batch_id: int,
    users: list[str],
    site: pywikibot.Site | None = None,
) -> None:
    """Post a talk-page notice to each user in *users* for a large job.

    No-op in dev / test mode.
    """
    if not _is_live():
        return

    if site is None:
        site = pywikibot.Site("commons", "commons")

    for username in users:
        try:
            talk = pywikibot.User(site, username).getUserTalkPage()
            notice = (
                f"\n\n== Chuckbot large job running ==\n"
                f"Chuckbot is currently running a large batch job "
                f"(Batch ID: {batch_id}).\n\n"
                f"If you notice any issues, please investigate or contact "
                f"[[User:Alachuckthebuck]].\n\n"
                f"Thanks! ~~~~"
            )
            talk.text = talk.text + notice
            talk.save(
                summary=f"Chuckbot large job notification (batch {batch_id})",
                minor=False,
                botflag=True,
            )
        except Exception:  # noqa: BLE001
            pass


def notify_bot_user(
    site: pywikibot.Site,
    username: str,
    batch_id: int,
    edit_count: int | None = None,
) -> None:
    """Post a rollback notice to a flagged bot's talk page.

    No-op in dev / test mode.
    """
    if not _is_live():
        return

    try:
        talk = pywikibot.User(site, username).getUserTalkPage()
        count_text = f" ({edit_count} edit(s))" if edit_count else ""
        notice = (
            f"\n\n== Chuckbot rollback notice ==\n"
            f"Hello,\n\n"
            f"One or more of your recent edits{count_text} were rolled back "
            f"by [[User:Chuckbot]] as part of a cleanup batch "
            f"(Batch ID: {batch_id}).\n\n"
            f"If this was unexpected, feel free to review or reach out to "
            f"[[User:Alachuckthebuck]].\n\n"
            f"Thanks! ~~~~"
        )
        talk.text = talk.text + notice
        talk.save(
            summary=f"Notification: edits rolled back (batch {batch_id})",
            minor=False,
            botflag=True,
        )
    except Exception:  # noqa: BLE001
        pass
