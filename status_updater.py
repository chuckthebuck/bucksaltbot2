"""Chuckbot on-wiki status page updates and talk-page notification helpers.

All functions that perform wiki edits are gated behind the ``NOTDEV``
environment variable (the same convention used elsewhere in this codebase).
When ``NOTDEV`` is unset the functions return immediately so that tests and
development environments never accidentally touch the live wiki.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from pywikibot_env import ensure_pywikibot_env
from redis_state import r as _redis
from botconfig import BOT_USERNAME, BOT_HELP_PAGE, STATUS_PAGE_PREFIX


def _pywikibot_unavailable(*args, **kwargs):
    raise RuntimeError("pywikibot is unavailable in this runtime")


_PYWIKIBOT_DIR_READY = ensure_pywikibot_env(strict=False) is not None

try:
    import pywikibot as _pywikibot  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    _pywikibot = None

if _pywikibot is None:
    pywikibot = SimpleNamespace(
        Site=_pywikibot_unavailable,
        Page=_pywikibot_unavailable,
        User=_pywikibot_unavailable,
    )
else:
    pywikibot = _pywikibot

_PYWIKIBOT_AVAILABLE = bool(_pywikibot)


def _log_status_debug(message: str) -> None:
    print(f"[status_updater] {message}", file=sys.stderr)


# ── Page titles ───────────────────────────────────────────────────────────────

# Status pages are maintained under User:<BOT_USERNAME>/status/* on the wiki.
STATUS_PAGE = STATUS_PAGE_PREFIX
NOTIFY_PAGE = f"{STATUS_PAGE_PREFIX}/notify"
STATUS_SUBPAGES = {
    "editing": f"{STATUS_PAGE}/editing",
    "web": f"{STATUS_PAGE}/web",
    "last_edit": f"{STATUS_PAGE}/last edit",
    "current_job": f"{STATUS_PAGE}/current job",
    "last_job": f"{STATUS_PAGE}/last job",
    "details": f"{STATUS_PAGE}/details",
    "warning": f"{STATUS_PAGE}/warning",
    "updated": f"{STATUS_PAGE}/updated",
}

# ── Redis key settings ────────────────────────────────────────────────────────

_NOTIFIED_BATCH_TTL = 7 * 24 * 3600  # 7 days


# ── Pywikibot OAuth configuration ─────────────────────────────────────────


# ── Database initialization and access ─────────────────────────────────────

def _get_authenticated_site() -> Any:
    if not _PYWIKIBOT_AVAILABLE:
        raise RuntimeError("pywikibot is unavailable in this runtime")

    if ensure_pywikibot_env(strict=False) is None:
        raise RuntimeError("Unable to initialize PYWIKIBOT_DIR")

    site = pywikibot.Site("commons", "commons")
    site.login()  

    return site

# ── Internal helpers ──────────────────────────────────────────────────────────


def _is_live() -> bool:
    """Return True when running in production (``NOTDEV`` is set)."""
    if os.environ.get("LIVE_TEST_DISABLE_STATUS_UPDATES"):
        _log_status_debug(
            "status updates disabled by LIVE_TEST_DISABLE_STATUS_UPDATES"
        )
        return False

    if not os.environ.get("NOTDEV"):
        _log_status_debug("status updates skipped because NOTDEV is not set")
        return False

    return True


def _save_status_subpage(site: Any, key: str, text: str) -> None:
    """Write a status field to its dedicated subpage."""
    page = pywikibot.Page(site, STATUS_SUBPAGES[key])
    page.text = text
    page.save(summary=f"Updating {BOT_USERNAME} status", minor=True, bot=True)


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


def get_notify_list(site: Any) -> list[str]:
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


def is_flagged_bot(site: Any, username: str) -> bool:
    """Return True if *username* has the ``bot`` user group on *site*."""
    try:
        return "bot" in pywikibot.User(site, username).groups()
    except Exception:  # noqa: BLE001
        return False


def get_last_bot_edit(
    site: Any = None,
    username: str | None = None,
) -> str:
    """Return the timestamp of the bot's most recent edit, or ``'Unknown'``."""
    try:
        if site is None:
            site = _get_authenticated_site()
        if username is None:
            username = site.username() or BOT_USERNAME
        user = pywikibot.User(site, username)
        contrib = next(user.contributions(total=1), None)
        if not contrib:
            return "Unknown"
        ts = contrib[2]
        return ts.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:  # noqa: BLE001
        return "Unknown"


def update_wiki_status(
    editing: str,
    web: str = "Online",
    *,
    site: Any = None,
    last_edit: str | None = None,
    current_job: str | None = None,
    last_job: str | None = None,
    details: str = "",
    warning: str | None = None,
    include_job_fields: bool = True,
) -> None:
    """Update {BOT_USERNAME} status subpages consumed by the on-wiki template."""
    if not _is_live():
        return

    try:
        active_site = site or _get_authenticated_site()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        resolved_last_edit = last_edit or get_last_bot_edit(active_site)

        fields = {
            "editing": editing,
            "web": web,
            "last_edit": resolved_last_edit,
            "details": details,
            # Always write the warning field so stale warnings are cleared.
            "warning": warning or "",
            "updated": now,
        }

        if include_job_fields:
            fields["current_job"] = current_job or "None"
            fields["last_job"] = last_job or "None"

        for key, value in fields.items():
            _save_status_subpage(active_site, key, value)
    except Exception as exc:  # noqa: BLE001
        _log_status_debug(f"update_wiki_status failed: {exc!r}")


def run_status_cron_update() -> None:
    """Refresh the status template from cron with a lightweight heartbeat."""
    update_wiki_status(
        editing="Idle",
        web="Online",
        details="Daily cron heartbeat",
        include_job_fields=False,
    )


def notify_maintainers(
    batch_id: int,
    users: list[str],
    site: Any = None,
) -> None:
    """Post a talk-page notice to each user in *users* for a large job.

    No-op in dev / test mode.
    """
    if not _is_live():
        return

    if site is None:
        site = _get_authenticated_site()

    for username in users:
        try:
            talk = pywikibot.User(site, username).getUserTalkPage()
            notice = (
                f"\n\n== {BOT_USERNAME} large job running ==\n"
                f"{BOT_USERNAME} is currently running a large batch job "
                f"(Batch ID: {batch_id}).\n\n"
                f"If you notice any issues, please investigate or contact "
                f"[[User:{BOT_HELP_PAGE}]].\n\n"
                f"Thanks! ~~~~"
            )
            talk.text = talk.text + notice
            talk.save(
                summary=f"{BOT_USERNAME} large job notification (batch {batch_id})",
                minor=False,
                bot=True,
            )
        except Exception:  # noqa: BLE001
            _log_status_debug(
                f"notify_maintainers failed for {username}: {sys.exc_info()[1]!r}"
            )


def notify_bot_user(
    site: Any,
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
            f"\n\n== {BOT_USERNAME} rollback notice ==\n"
            f"Hello,\n\n"
            f"One or more of your recent edits{count_text} were rolled back "
            f"by [[User:{BOT_USERNAME}]] as part of a cleanup batch "
            f"(Batch ID: {batch_id}).\n\n"
            f"If this was unexpected, feel free to review or reach out to "
            f"[[User:{BOT_HELP_PAGE}]].\n\n"
            f"Thanks! ~~~~"
        )
        talk.text = talk.text + notice
        talk.save(
            summary=f"Notification: edits rolled back (batch {batch_id})",
            minor=False,
            bot=True,
        )
    except Exception as exc:  # noqa: BLE001
        _log_status_debug(f"notify_bot_user failed for {username}: {exc!r}")


if __name__ == "__main__":
    run_status_cron_update()
