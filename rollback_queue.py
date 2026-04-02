import os
from celery import shared_task
from pywikibot_env import ensure_pywikibot_env
from redis_state import set_progress, update_progress
from toolsdb import get_conn, TABLE_JOBS, TABLE_JOB_ITEMS
from botconfig import BOT_NAME
from framework.action import get_registered_action
import status_updater


ensure_pywikibot_env(strict=True)

import pywikibot


# MediaWiki API error codes that mean the rollback is already in the desired
# state.  The page does not need to change, so these are not real failures.
_ROLLBACK_NOOP_CODES = frozenset({"alreadyrolled", "onlyauthor"})


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


def _summary_with_requester(summary: str | None, requested_by: str) -> str:
    """Append requester attribution to rollback summary when missing."""
    requester_tag = f"requested-by={requested_by}"
    base = (summary or "").strip()

    if not base:
        return f"Mass rollback via bucksaltbot queue; {requester_tag}"

    if requester_tag in base:
        return base

    return f"{base}; {requester_tag}"


def _fetch_job_meta(job_id: int):
    """Return bot_jobs row without preloading bot_job_items."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, requested_by, status, dry_run, batch_id
                FROM {TABLE_JOBS}
                WHERE id=%s
                """,
                (job_id,),
            )
            return cursor.fetchone()


def _update_job_status(job_id: int, status: str):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE {TABLE_JOBS} SET status=%s WHERE id=%s",
                (status, job_id),
            )
        conn.commit()


def _count_batch_jobs(batch_id: int) -> int:
    """Return the number of Celery jobs that share *batch_id*."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {TABLE_JOBS} WHERE batch_id=%s",
                (batch_id,),
            )
            row = cursor.fetchone()
    return int(row[0]) if row else 0


def _update_item(item_id: int, status: str, error: str | None = None):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE {TABLE_JOB_ITEMS} SET status=%s, error=%s WHERE id=%s",
                (status, error, item_id),
            )
        conn.commit()


def _count_job_items(job_id: int) -> int:
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) FROM {TABLE_JOB_ITEMS} WHERE job_id=%s",
                (job_id,),
            )
            row = cursor.fetchone()
    return int(row[0]) if row else 0


def _get_item_status_counts(job_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT status, COUNT(*)
                FROM {TABLE_JOB_ITEMS}
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
                        f"""
                        SELECT id, file_title, target_user, summary
                        FROM {TABLE_JOB_ITEMS}
                        WHERE job_id=%s AND status='queued'
                        ORDER BY id ASC
                        LIMIT 1
                        """,
                        (job_id,),
                    )
                else:
                    if preferred_batch_id is None:
                        cursor.execute(
                            f"""
                            SELECT i.id, i.job_id, i.file_title, i.target_user, i.summary
                            FROM {TABLE_JOB_ITEMS} i
                            JOIN {TABLE_JOBS} j ON j.id = i.job_id
                            WHERE i.status='queued' AND j.status IN ('queued', 'running')
                            ORDER BY i.id ASC
                            LIMIT 1
                            """
                        )
                    else:
                        cursor.execute(
                            f"""
                            SELECT i.id, i.job_id, i.file_title, i.target_user, i.summary
                            FROM {TABLE_JOB_ITEMS} i
                            JOIN {TABLE_JOBS} j ON j.id = i.job_id
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
                cursor.execute(
                    f"""
                    UPDATE {TABLE_JOB_ITEMS}
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
            raise RuntimeError(
                "Login did not establish an authenticated user session"
            )
        print("Logged in as:", logged_user)
    except Exception as e:
        print(f"OAuth login failed: {_format_exception(e)}")
        raise

    return site


@shared_task(ignore_result=True)
def process_rollback_job(job_id: int):
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
                            f"""
                            UPDATE {TABLE_JOB_ITEMS}
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
            else:
                item_id, claimed_job_id, file_title, target_user, summary = claimed

            claimed_job = _fetch_job_meta(claimed_job_id)
            if not claimed_job:
                _update_item(item_id, "failed", "Missing bot_jobs row")
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
                    _update_item(item_id, "completed", None)
                    update_progress(claimed_job_id, "completed")
                    continue

                get_registered_action().execute_item(
                    item_key=file_title,
                    item_target=target_user,
                    summary=summary,
                    requested_by=claimed_requested_by,
                    site=site,
                    dry_run=bool(claimed_dry_run),
                )

                _update_item(item_id, "completed", None)
                update_progress(claimed_job_id, "completed")

                # Track flagged-bot accounts for post-batch notification.
                if site and status_updater.is_flagged_bot(site, target_user):
                    notified_bots[target_user] = notified_bots.get(target_user, 0) + 1

            except Exception as exc:  # noqa: BLE001
                err_str = _format_exception(exc)
                if any(code in err_str for code in _ROLLBACK_NOOP_CODES):
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
                    f"""
                    UPDATE {TABLE_JOB_ITEMS}
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


@shared_task(name=f"{BOT_NAME}.resolve_diff_rollback_job", ignore_result=True)
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
