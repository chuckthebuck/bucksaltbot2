import json
import os
import time
from celery import shared_task
from pywikibot_env import ensure_pywikibot_env
from redis_state import set_progress, update_progress
from toolsdb import get_conn, get_runtime_config
import status_updater


ensure_pywikibot_env(strict=True)

import pywikibot  # noqa: E402


# The queue stores one row per target page, while Celery jobs may process rows
# across the whole batch.  Keep helpers small so the worker can refresh state
# between items and react quickly to cancellation.

# MediaWiki API error codes that mean the rollback is already in the desired
# state.  The page does not need to change, so these are not real failures.
_ROLLBACK_NOOP_CODES = frozenset({"alreadyrolled", "onlyauthor"})
_ROLLBACK_NOT_CURRENT_CODES = frozenset({"alreadyrolled"})
_ROLLBACK_NOT_CURRENT_PHRASES = (
    "not the latest",
    "current revision",
    "current version",
    "last contributor",
)
_ROLLBACK_EDIT_SUMMARY_TEMPLATE_KEY = "edit_summary_template"
_ROLLBACK_EDIT_SUMMARY_ENV_KEY = "ROLLBACK_EDIT_SUMMARY_TEMPLATE"
_ROLLBACK_THROUGH_BOT_CONFIG_KEY = "ROLLBACK_THROUGH_BOT_USERS"
_ROLLBACK_THROUGH_BOT_CACHE_TTL = 60
_rollback_through_bot_cache: tuple[set[str] | None, float] = (None, 0.0)


def _format_exception(exc: Exception) -> str:
    """Return a useful non-empty error string for storage and logs."""
    text = str(exc).strip()
    if text:
        return text

    args = getattr(exc, "args", ())
    if args:
        joined = ", ".join(str(a) for a in args if str(a).strip())
        if joined:
            return f"{exc.__class__.__name__}: {joined}"

    rendered = repr(exc).strip()
    if rendered and rendered != f"{exc.__class__.__name__}()":
        return f"{exc.__class__.__name__}: {rendered}"

    return exc.__class__.__name__


def _looks_like_not_current_rollback(error_text: str) -> bool:
    normalized = str(error_text or "").casefold()
    return any(code in normalized for code in _ROLLBACK_NOT_CURRENT_CODES) or any(
        phrase in normalized for phrase in _ROLLBACK_NOT_CURRENT_PHRASES
    )


class _SummaryFields(dict):
    """Format-map fields that collapse missing optional values to an empty string."""

    def __missing__(self, key: str) -> str:
        return ""


def _configured_rollback_edit_summary_template() -> str | None:
    """Return a module-configured rollback edit summary template, if present."""
    env_template = os.getenv(_ROLLBACK_EDIT_SUMMARY_ENV_KEY)
    if env_template and env_template.strip():
        return env_template.strip()

    try:
        from router.module_registry import get_module_config

        value = get_module_config("rollback").get(_ROLLBACK_EDIT_SUMMARY_TEMPLATE_KEY)
    except Exception:
        value = None

    value = str(value or "").strip()
    return value or None


def _summary_with_requester(
    summary: str | None,
    requested_by: str,
    *,
    batch_id: int | str | None = None,
    job_id: int | str | None = None,
    title: str | None = None,
    target_user: str | None = None,
    action: str = "rollback",
    revision_id: int | str | None = None,
) -> str:
    """Build a rollback edit summary with requester and queue metadata."""
    requester_tag = f"requested-by={requested_by}"
    base = (summary or "").strip() or "Mass rollback via bucksaltbot queue"

    template = _configured_rollback_edit_summary_template()
    if template:
        fields = _SummaryFields(
            summary=base,
            requested_by=requested_by,
            requester=requested_by,
            batch_id="" if batch_id is None else str(batch_id),
            batch="" if batch_id is None else str(batch_id),
            job_id="" if job_id is None else str(job_id),
            job="" if job_id is None else str(job_id),
            title=title or "",
            page=title or "",
            target_user=target_user or "",
            user=target_user or "",
            action=action,
            revision_id="" if revision_id is None else str(revision_id),
        )
        rendered = template.format_map(fields).strip()
        return rendered or base

    parts = [base]

    if requester_tag in base:
        requester_tag = ""
    if requester_tag:
        parts.append(requester_tag)
    if batch_id not in (None, ""):
        parts.append(f"batch={batch_id}")
    if job_id not in (None, ""):
        parts.append(f"job={job_id}")

    return "; ".join(parts)


def _restore_creation_revision(
    site: pywikibot.Site,
    title: str,
    revision_id: int,
    summary: str | None,
    requested_by: str,
    *,
    batch_id: int | str | None = None,
    job_id: int | str | None = None,
) -> None:
    """Restore a creator-only page to its initial revision."""
    page = pywikibot.Page(site, title)
    original_text = page.getOldVersion(int(revision_id))
    if page.get() == original_text:
        return
    page.text = original_text
    page.save(
        summary=_summary_with_requester(
            summary or f"Restoring creator-only page to creation revision {revision_id}",
            requested_by,
            batch_id=batch_id,
            job_id=job_id,
            title=title,
            action="restore_creation",
            revision_id=revision_id,
        ),
        minor=False,
    )


def _revision_user(revision: dict) -> str:
    return str(revision.get("user") or "").strip()


def _parse_configured_bot_users(raw_value: str | None) -> set[str]:
    if not raw_value:
        return set()

    value = str(raw_value).strip()
    if not value:
        return set()

    candidates: list[str]
    if value.startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = []
        candidates = [str(item) for item in parsed] if isinstance(parsed, list) else []
    else:
        candidates = [part.strip() for part in value.replace("\n", ",").split(",")]

    return {candidate.casefold() for candidate in candidates if candidate.strip()}


def _configured_rollback_through_bot_users() -> set[str] | None:
    """Return configured bot allowlist, or None when no allowlist is configured."""
    global _rollback_through_bot_cache

    cached_users, expires_at = _rollback_through_bot_cache
    if time.time() < expires_at:
        return cached_users

    env_users = _parse_configured_bot_users(os.getenv(_ROLLBACK_THROUGH_BOT_CONFIG_KEY))
    runtime_users = set()
    try:
        rows = get_runtime_config([_ROLLBACK_THROUGH_BOT_CONFIG_KEY])
        runtime_users = _parse_configured_bot_users(
            rows.get(_ROLLBACK_THROUGH_BOT_CONFIG_KEY)
        )
    except Exception:
        runtime_users = set()

    configured = env_users | runtime_users
    result = configured if configured else None
    _rollback_through_bot_cache = (
        result,
        time.time() + _ROLLBACK_THROUGH_BOT_CACHE_TTL,
    )
    return result


def _revision_is_bot(site: pywikibot.Site, revision: dict) -> bool:
    user = _revision_user(revision)
    if not user:
        return False
    configured_users = _configured_rollback_through_bot_users()
    if configured_users is not None:
        return user.casefold() in configured_users
    if revision.get("bot") is True:
        return True
    try:
        return bool(status_updater.is_flagged_bot(site, user))
    except Exception:
        return False


def _fetch_recent_revisions(site: pywikibot.Site, title: str, limit: int = 50) -> list[dict]:
    request = site.simple_request(
        action="query",
        prop="revisions",
        titles=title,
        rvlimit=str(limit),
        rvprop="ids|user|flags",
        rvdir="older",
        formatversion="2",
    )
    data = request.submit()
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return []
    revisions = pages[0].get("revisions") or []
    return [revision for revision in revisions if isinstance(revision, dict)]


def _restore_revision_text(
    site: pywikibot.Site,
    title: str,
    revision_id: int,
    summary: str | None,
    requested_by: str,
    *,
    batch_id: int | str | None = None,
    job_id: int | str | None = None,
) -> None:
    page = pywikibot.Page(site, title)
    target_text = page.getOldVersion(int(revision_id))
    if page.get() == target_text:
        return
    page.text = target_text
    page.save(
        summary=_summary_with_requester(
            summary or f"Rollback through bot edits to pre-vandal revision {revision_id}",
            requested_by,
            batch_id=batch_id,
            job_id=job_id,
            title=title,
            action="rollback_through_bots",
            revision_id=revision_id,
        ),
        minor=False,
    )


def _rollback_through_bot_edits(
    site: pywikibot.Site,
    title: str,
    target_user: str,
    summary: str | None,
    requested_by: str,
    *,
    batch_id: int | str | None = None,
    job_id: int | str | None = None,
) -> bool:
    """Restore to the revision before the target user's edits under top bot edits."""
    target_key = target_user.strip().casefold()
    if not target_key:
        return False

    revisions = _fetch_recent_revisions(site, title)
    skipped_bot_edit = False
    target_parent_id = None
    found_target = False

    for revision in revisions:
        user_key = _revision_user(revision).casefold()
        if not found_target:
            if user_key == target_key:
                found_target = True
                target_parent_id = revision.get("parentid")
                continue
            if _revision_is_bot(site, revision):
                skipped_bot_edit = True
                continue
            return False

        if user_key == target_key:
            target_parent_id = revision.get("parentid")
            continue
        break

    if not skipped_bot_edit or not found_target or not target_parent_id:
        return False

    _restore_revision_text(
        site,
        title,
        int(target_parent_id),
        summary,
        requested_by,
        batch_id=batch_id,
        job_id=job_id,
    )
    return True


def _fetch_job_meta(job_id: int):
    """Return rollback_jobs row without preloading rollback_job_items."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, requested_by, status, dry_run, batch_id
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )
            return cursor.fetchone()


def _update_job_status(job_id: int, status: str):
    """Write the aggregate job status."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE rollback_jobs SET status=%s WHERE id=%s",
                (status, job_id),
            )
        conn.commit()


def _count_batch_jobs(batch_id: int) -> int:
    """Return the number of Celery jobs that share *batch_id*."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM rollback_jobs WHERE batch_id=%s",
                (batch_id,),
            )
            row = cursor.fetchone()
    return int(row[0]) if row else 0


def _update_item(item_id: int, status: str, error: str | None = None):
    """Write the status for a single rollback target."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE rollback_job_items SET status=%s, error=%s WHERE id=%s",
                (status, error, item_id),
            )
        conn.commit()


def _count_job_items(job_id: int) -> int:
    """Return the total number of item rows for a rollback job."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM rollback_job_items WHERE job_id=%s",
                (job_id,),
            )
            row = cursor.fetchone()
    return int(row[0]) if row else 0


def _get_item_status_counts(job_id: int) -> dict[str, int]:
    """Return item-status counts used to derive the aggregate job status."""
    counts: dict[str, int] = {}
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, COUNT(*)
                FROM rollback_job_items
                WHERE job_id=%s
                GROUP BY status
                """,
                (job_id,),
            )
            for status, count in cursor.fetchall():
                counts[str(status)] = int(count)
    return counts


def _derive_job_status_from_items(job_id: int) -> tuple[str, dict[str, int]]:
    """Derive rollback_jobs.status from rollback_job_items state."""
    counts = _get_item_status_counts(job_id)
    total = sum(counts.values())
    failed = counts.get("failed", 0)
    queued = counts.get("queued", 0)
    running = counts.get("running", 0)
    completed = counts.get("completed", 0)
    canceled = counts.get("canceled", 0)

    if total == 0:
        return "completed", counts
    if failed:
        return "failed", counts
    if queued or running:
        return "running", counts
    if canceled and not completed:
        return "canceled", counts
    if canceled and completed:
        return "canceled", counts
    return "completed", counts


def claim_next_item(job_id: int | None = None, preferred_batch_id: int | None = None):
    """Claim one queued item by transitioning it to running.

    When ``job_id`` is provided, claims from that job only.
    When ``job_id`` is None, claims from the global queue and optionally
    prioritizes items whose job has ``preferred_batch_id``.

    Returns:
      - job-scoped claim: (id, file_title, target_user, summary)
      - global claim: (id, claimed_job_id, file_title, target_user, summary)
      - None when no queued items remain.
    """
    while True:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                if job_id is not None:
                    cursor.execute(
                        """
                        SELECT id, file_title, target_user, summary,
                               item_action, restore_revision_id, rollback_through_bots
                        FROM rollback_job_items
                        WHERE job_id=%s AND status='queued'
                        ORDER BY id ASC
                        LIMIT 1
                        """,
                        (job_id,),
                    )
                else:
                    if preferred_batch_id is None:
                        cursor.execute(
                            """
                            SELECT i.id, i.job_id, i.file_title, i.target_user, i.summary,
                                   i.item_action, i.restore_revision_id,
                                   i.rollback_through_bots
                            FROM rollback_job_items i
                            JOIN rollback_jobs j ON j.id = i.job_id
                            WHERE i.status='queued' AND j.status IN ('queued', 'running')
                            ORDER BY i.id ASC
                            LIMIT 1
                            """
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT i.id, i.job_id, i.file_title, i.target_user, i.summary,
                                   i.item_action, i.restore_revision_id,
                                   i.rollback_through_bots
                            FROM rollback_job_items i
                            JOIN rollback_jobs j ON j.id = i.job_id
                            WHERE i.status='queued' AND j.status IN ('queued', 'running')
                            ORDER BY
                                CASE WHEN j.batch_id=%s THEN 0 ELSE 1 END,
                                i.id ASC
                            LIMIT 1
                            """,
                            (preferred_batch_id,),
                        )
                item = cursor.fetchone()

                if not item:
                    return None

                item_id = item[0]
                # The WHERE status='queued' guard makes this a compare-and-set
                # claim.  If another worker won the race, rowcount is 0 and the
                # loop simply looks for the next queued item.
                cursor.execute(
                    """
                    UPDATE rollback_job_items
                    SET status='running', error=NULL, attempts=attempts+1
                    WHERE id=%s AND status='queued'
                    """,
                    (item_id,),
                )

                if cursor.rowcount == 1:
                    conn.commit()
                    return item

            conn.commit()


def _bot_site() -> pywikibot.Site:
    """Create and authenticate a Pywikibot Site using OAuth env vars."""
    if os.environ.get("CHUCKBOT_LOCAL_SAFE_MODE"):
        raise RuntimeError("Local safe mode blocks authenticated wiki editing")

    ensure_pywikibot_env(strict=True)

    consumer_token = os.environ.get("CONSUMER_TOKEN")
    consumer_secret = os.environ.get("CONSUMER_SECRET")
    access_token = os.environ.get("ACCESS_TOKEN")
    access_secret = os.environ.get("ACCESS_SECRET")

    if not all([consumer_token, consumer_secret, access_token, access_secret]):
        raise RuntimeError(
            "CONSUMER_TOKEN, CONSUMER_SECRET, ACCESS_TOKEN and ACCESS_SECRET must be configured"
        )

    site = pywikibot.Site("commons", "commons")

    # Authenticate with OAuth
    try:
        site.login()
        logged_user = site.user()
        if not logged_user:
            raise RuntimeError("Login did not establish an authenticated user session")
        print("Logged in as:", logged_user)
    except Exception as e:
        print(f"OAuth login failed: {_format_exception(e)}")
        raise

    return site


@shared_task(ignore_result=True)
def process_rollback_job(job_id: int):
    """Process queued rollback items, updating DB progress and wiki status."""
    site = None
    try:
        job = _fetch_job_meta(job_id)

        if not job:
            return

        _, requested_by, current_status, dry_run, batch_id = job

        if current_status == "canceled":
            return

        total_items = _count_job_items(job_id)

        _update_job_status(job_id, "running")
        set_progress(
            job_id,
            {"status": "running", "total": total_items, "completed": 0, "failed": 0},
        )

        if not dry_run:
            site = _bot_site()

        # Determine whether this is a large job (batch spans multiple chunks).
        job_count = _count_batch_jobs(batch_id)
        large = status_updater.is_large_job(job_count)

        # Fetch the notify list once for large jobs; reused for warning text and
        # for the actual talk-page notifications below.
        notify_users: list[str] = []
        if large:
            if site is None:
                ensure_pywikibot_env(strict=True)
            _notify_site = site or pywikibot.Site("commons", "commons")
            notify_users = status_updater.get_notify_list(_notify_site)

        # Build warning text for large jobs.
        warning_text: str | None = None
        if large:
            user_links = ", ".join(f"[[User:{u}|{u}]]" for u in notify_users)
            warning_text = "Large batch job in progress. " + (
                f"If issues occur, please contact: {user_links}"
                if user_links
                else "If issues occur, please contact [[User:Alachuckthebuck]]."
            )

        status_updater.update_wiki_status(
            editing="Actively editing",
            site=site,
            current_job=f"Processing batch {batch_id} (job {job_id})",
            details=f"{total_items} items queued",
            warning=warning_text,
        )

        # Notify maintainers once per large batch.
        if large and not status_updater.is_batch_already_notified(batch_id):
            if site is None:
                ensure_pywikibot_env(strict=True)
            _notify_site = site or pywikibot.Site("commons", "commons")
            status_updater.notify_maintainers(batch_id, notify_users, site=_notify_site)
            status_updater.mark_batch_notified(batch_id)

        # Track flagged-bot users rolled back in this job: username → edit count.
        notified_bots: dict[str, int] = {}

        while True:
            refreshed_job = _fetch_job_meta(job_id)

            if refreshed_job and refreshed_job[2] == "canceled":
                with get_conn() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            """
                            UPDATE rollback_job_items
                            SET status='canceled', error='Canceled by requester'
                            WHERE job_id=%s AND status IN ('queued', 'running')
                            """,
                            (job_id,),
                        )
                    conn.commit()
                break

            claimed = claim_next_item(job_id=None, preferred_batch_id=batch_id)
            if not claimed:
                break

            if len(claimed) == 4:
                # Backward-compatible tuple shape for tests and job-scoped calls.
                item_id, file_title, target_user, summary = claimed
                claimed_job_id = job_id
                item_action = "rollback"
                restore_revision_id = None
                rollback_through_bots = False
            elif len(claimed) == 6:
                (
                    item_id,
                    file_title,
                    target_user,
                    summary,
                    item_action,
                    restore_revision_id,
                ) = claimed
                claimed_job_id = job_id
                rollback_through_bots = False
            elif len(claimed) == 7:
                (
                    item_id,
                    file_title,
                    target_user,
                    summary,
                    item_action,
                    restore_revision_id,
                    rollback_through_bots,
                ) = claimed
                claimed_job_id = job_id
            else:
                (
                    item_id,
                    claimed_job_id,
                    file_title,
                    target_user,
                    summary,
                    item_action,
                    restore_revision_id,
                    rollback_through_bots,
                ) = claimed

            # Claims can come from sibling jobs in the same batch, so refresh
            # the owning job before deciding whether this item is still editable.
            claimed_job = _fetch_job_meta(claimed_job_id)
            if not claimed_job:
                _update_item(item_id, "failed", "Missing rollback_jobs row")
                continue

            (
                _,
                claimed_requested_by,
                claimed_job_status,
                claimed_dry_run,
                _claimed_batch_id,
            ) = claimed_job

            if claimed_job_status == "queued":
                _update_job_status(claimed_job_id, "running")

            _update_item(item_id, "running", None)

            try:
                if claimed_dry_run:
                    # Dry-runs exercise queue/progress flow without touching the wiki.
                    _update_item(item_id, "completed", None)
                    update_progress(claimed_job_id, "completed")
                    continue

                if item_action == "restore_creation":
                    # Some from-diff jobs represent page creation rather than a
                    # normal rollback-able edit; restore the creation revision.
                    if not restore_revision_id:
                        raise RuntimeError("Missing creation revision for restore item")
                    _restore_creation_revision(
                        site,
                        file_title,
                        int(restore_revision_id),
                        summary,
                        claimed_requested_by,
                        batch_id=_claimed_batch_id,
                        job_id=claimed_job_id,
                    )
                else:
                    token = site.tokens["rollback"]

                    site.simple_request(
                        action="rollback",
                        title=file_title,
                        user=target_user,
                        token=token,
                        summary=_summary_with_requester(
                            summary,
                            claimed_requested_by,
                            batch_id=_claimed_batch_id,
                            job_id=claimed_job_id,
                            title=file_title,
                            target_user=target_user,
                            action="rollback",
                        ),
                        markbot=True,
                        bot=True,
                    ).submit()

                _update_item(item_id, "completed", None)
                update_progress(claimed_job_id, "completed")

                # Track flagged-bot accounts for post-batch notification.
                if site and status_updater.is_flagged_bot(site, target_user):
                    notified_bots[target_user] = notified_bots.get(target_user, 0) + 1

            except Exception as exc:  # noqa: BLE001
                err_str = _format_exception(exc)
                if (
                    rollback_through_bots
                    and _looks_like_not_current_rollback(err_str)
                    and _rollback_through_bot_edits(
                        site,
                        file_title,
                        target_user,
                        summary,
                        claimed_requested_by,
                        batch_id=_claimed_batch_id,
                        job_id=claimed_job_id,
                    )
                ):
                    _update_item(item_id, "completed", "Rolled back through bot edits")
                    update_progress(claimed_job_id, "completed")
                elif any(code in err_str for code in _ROLLBACK_NOOP_CODES):
                    # Page is already in the desired state – not a real failure.
                    _update_item(item_id, "completed", err_str)
                    update_progress(claimed_job_id, "completed")
                else:
                    _update_item(item_id, "failed", err_str)
                    update_progress(claimed_job_id, "failed")

        # Notify each flagged-bot account that was rolled back (once per job).
        if site:
            for bot_user, count in notified_bots.items():
                status_updater.notify_bot_user(
                    site, bot_user, batch_id, edit_count=count
                )

        # AFTER the loop finishes
        final_status, counts = _derive_job_status_from_items(job_id)
        completed_count = counts.get("completed", 0)
        failed_count = counts.get("failed", 0)
        total_count = sum(counts.values())

        set_progress(
            job_id,
            {
                "status": final_status,
                "total": total_count,
                "completed": completed_count,
                "failed": failed_count,
            },
        )

        _update_job_status(job_id, final_status)

        status_updater.update_wiki_status(
            editing="Idle",
            site=site,
            last_job=(
                f"Failed batch {batch_id} (job {job_id})"
                if final_status == "failed"
                else (
                    f"Canceled batch {batch_id} (job {job_id})"
                    if final_status == "canceled"
                    else f"Completed batch {batch_id} (job {job_id})"
                )
            ),
            details=f"{completed_count}/{total_count} items completed",
        )

    except Exception as exc:
        error_text = _format_exception(exc)
        with get_conn() as conn:
            with conn.cursor() as cursor:
                # Mark any in-flight or pending items failed with the task-level error.
                cursor.execute(
                    """
                    UPDATE rollback_job_items
                    SET status='failed', error=%s
                    WHERE job_id=%s AND status IN ('queued', 'running')
                    """,
                    (error_text, job_id),
                )
            conn.commit()

        final_status, counts = _derive_job_status_from_items(job_id)
        set_progress(
            job_id,
            {
                "status": final_status,
                "total": sum(counts.values()),
                "completed": counts.get("completed", 0),
                "failed": counts.get("failed", 0),
            },
        )

        _update_job_status(job_id, "failed")

        status_updater.update_wiki_status(
            editing="Error",
            site=site,
            details=error_text[:200],
        )

        raise


@shared_task(name="buckbot.resolve_diff_rollback_job", ignore_result=True)
def resolve_diff_rollback_job_task(job_id: int):
    """Resolve a from-diff job into rollback_job_items.

    This task lives in rollback_queue.py because the worker always imports this
    module at startup. That guarantees registration of the task name used by
    web requests, even when route modules are not loaded in a particular
    worker process.
    """
    from router import resolve_diff_rollback_job_impl

    resolve_diff_rollback_job_impl(job_id)


@shared_task(name="router.resolve_diff_rollback_job", ignore_result=True)
def resolve_diff_rollback_job_task_legacy(job_id: int):
    """Legacy task-name alias for already-queued resolver messages."""
    resolve_diff_rollback_job_task(job_id)
