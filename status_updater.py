"""Chuckbot on-wiki status page updates and talk-page notification helpers.

All functions that perform wiki edits are gated behind the ``NOTDEV``
environment variable (the same convention used elsewhere in this codebase).
When ``NOTDEV`` is unset the functions return immediately so that tests and
development environments never accidentally touch the live wiki.
"""
from __future__ import annotations

import os
import pywikibot


import os
from datetime import datetime, timezone
from pathlib import Path
from redis_state import r as _redis


def _resolve_pywikibot_dir() -> Path:
    """Return a writable directory for Pywikibot config files."""
    candidates: list[Path] = []

    env_dir = os.environ.get("PYWIKIBOT_DIR")
    if env_dir:
        candidates.append(Path(env_dir))

    home = os.environ.get("HOME")
    if home and home != "/":
        candidates.append(Path(home) / ".pywikibot")

    candidates.append(Path("/workspace") / ".pywikibot")
    candidates.append(Path("/tmp") / f".pywikibot-{os.getuid()}")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue

    raise RuntimeError("No writable directory available for PYWIKIBOT_DIR")


def _bootstrap_pywikibot_env() -> None:
    """Set PYWIKIBOT_DIR before importing pywikibot.

    Pywikibot reads config paths during import. On Toolforge, defaulting to
    /workspace can trigger ownership warnings, so force a safe home path first.
    """
    pywikibot_home = _resolve_pywikibot_dir()
    os.environ["PYWIKIBOT_DIR"] = str(pywikibot_home)

    config_file = pywikibot_home / "user-config.py"
    if not config_file.exists():
        config_file.write_text(
            "family = 'commons'\n"
            "mylang = 'commons'\n"
            "usernames['commons']['commons'] = 'Chuckbot'\n"
        )


_bootstrap_pywikibot_env()


# ── Page titles ───────────────────────────────────────────────────────────────

# Status pages are maintained under User:Chuckbot/status/* on Commons.
STATUS_PAGE = "User:Chuckbot/status"
NOTIFY_PAGE = "User:Chuckbot/status/notify"
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


def _setup_pywikibot_dir() -> None:
    """Configure Pywikibot to use ~/.pywikibot for config files.

    This ensures Pywikibot uses the home directory instead of /workspace,
    which avoids file ownership issues on Toolforge.
    """
    pywikibot_home = _resolve_pywikibot_dir()
    os.environ["PYWIKIBOT_DIR"] = str(pywikibot_home)

    # Create minimal config if it doesn't exist
    config_file = pywikibot_home / "user-config.py"
    if not config_file.exists():
        config_file.write_text(
            "family = 'commons'\n"
            "mylang = 'commons'\n"
            "usernames['commons']['commons'] = 'Chuckbot'\n"
        )


# ── Database initialization and access ─────────────────────────────────────

def _get_authenticated_site() -> pywikibot.Site:
    _setup_pywikibot_dir()

    site = pywikibot.Site("commons", "commons")
    site.login()  

    return site

# ── Internal helpers ──────────────────────────────────────────────────────────


def _is_live() -> bool:
    """Return True when running in production (``NOTDEV`` is set)."""
    if os.environ.get("LIVE_TEST_DISABLE_STATUS_UPDATES"):
        return False
    return bool(os.environ.get("NOTDEV"))


def _save_status_subpage(site: pywikibot.Site, key: str, text: str) -> None:
    """Write a status field to its dedicated subpage."""
    page = pywikibot.Page(site, STATUS_SUBPAGES[key])
    page.text = text
    page.save(summary="Updating Chuckbot status", minor=True, botflag=True)


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


def get_last_bot_edit(
    site: pywikibot.Site | None = None,
    username: str | None = None,
) -> str:
    """Return the timestamp of the bot's most recent edit, or ``'Unknown'``."""
    try:
        if site is None:
            site = _get_authenticated_site()
        if username is None:
            username = site.username() or "Chuckbot"
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
    last_edit: str | None = None,
    current_job: str | None = None,
    last_job: str | None = None,
    details: str = "",
    warning: str | None = None,
) -> None:
    """Update Chuckbot status subpages consumed by the on-wiki template."""
    if not _is_live():
        return

    try:
        site = _get_authenticated_site()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        resolved_last_edit = last_edit or get_last_bot_edit(site)

        fields = {
            "editing": editing,
            "web": web,
            "last_edit": resolved_last_edit,
            "current_job": current_job or "None",
            "last_job": last_job or "None",
            "details": details,
            # Always write the warning field so stale warnings are cleared.
            "warning": warning or "",
            "updated": now,
        }

        for key, value in fields.items():
            _save_status_subpage(site, key, value)
    except Exception:  # noqa: BLE001
        pass


def run_status_cron_update() -> None:
    """Refresh the status template from cron with a lightweight heartbeat."""
    update_wiki_status(
        editing="Idle",
        web="Online",
        details="Daily cron heartbeat",
    )


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
        site = _get_authenticated_site()

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


if __name__ == "__main__":
    run_status_cron_update()
