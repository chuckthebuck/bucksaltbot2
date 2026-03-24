import os
from celery import shared_task
import pywikibot
from redis_state import set_progress, update_progress
from toolsdb import get_conn
import status_updater


def _fetch_job(job_id: int):
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
            job = cursor.fetchone()

            if not job:
                return None, []

            cursor.execute(
                """
                SELECT id, file_title, target_user, summary
                FROM rollback_job_items
                WHERE job_id=%s
                ORDER BY id ASC
                """,
                (job_id,),
            )

            items = cursor.fetchall()

    return job, items


def _update_job_status(job_id: int, status: str):
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
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE rollback_job_items SET status=%s, error=%s WHERE id=%s",
                (status, error, item_id),
            )
        conn.commit()


def _bot_site() -> pywikibot.Site:
    consumer_token = os.environ.get("CONSUMER_TOKEN")
    consumer_secret = os.environ.get("CONSUMER_SECRET")
    access_token = os.environ.get("ACCESS_TOKEN")
    access_secret = os.environ.get("ACCESS_SECRET")

    if not all([consumer_token, consumer_secret, access_token, access_secret]):
        raise RuntimeError(
            "CONSUMER_TOKEN, CONSUMER_SECRET, ACCESS_TOKEN and ACCESS_SECRET must be configured"
        )

    site = pywikibot.Site("commons", "commons")
    site.login()

    print("Logged in as:", site.user())

    return site


@shared_task(ignore_result=True)
def process_rollback_job(job_id: int):
    try:
        job, items = _fetch_job(job_id)

        if not job:
            return

        _, requested_by, current_status, dry_run, batch_id = job

        if current_status == "canceled":
            return

        _update_job_status(job_id, "running")
        set_progress(
            job_id,
            {"status": "running", "total": len(items), "completed": 0, "failed": 0},
        )

        site = None
        if not dry_run:
            site = _bot_site()

        # Determine whether this is a large job (batch spans multiple chunks).
        job_count = _count_batch_jobs(batch_id)
        large = status_updater.is_large_job(job_count)

        # Fetch the notify list once for large jobs; reused for warning text and
        # for the actual talk-page notifications below.
        notify_users: list[str] = []
        if large:
            _notify_site = site or pywikibot.Site("commons", "commons")
            notify_users = status_updater.get_notify_list(_notify_site)

        # Build warning text for large jobs.
        warning_text: str | None = None
        if large:
            user_links = ", ".join(f"[[User:{u}|{u}]]" for u in notify_users)
            warning_text = (
                "Large batch job in progress. "
                + (
                    f"If issues occur, please contact: {user_links}"
                    if user_links
                    else "If issues occur, please contact [[User:Alachuckthebuck]]."
                )
            )

        status_updater.update_wiki_status(
            editing="Actively editing",
            current_job=f"Processing batch {batch_id} (job {job_id})",
            details=f"{len(items)} items queued",
            warning=warning_text,
        )

        # Notify maintainers once per large batch.
        if large and not status_updater.is_batch_already_notified(batch_id):
            _notify_site = site or pywikibot.Site("commons", "commons")
            status_updater.notify_maintainers(batch_id, notify_users, site=_notify_site)
            status_updater.mark_batch_notified(batch_id)

        failed = 0
        # Track flagged-bot users rolled back in this job: username → edit count.
        notified_bots: dict[str, int] = {}

        for item_id, file_title, target_user, summary in items:
            refreshed_job, _ = _fetch_job(job_id)

            if refreshed_job and refreshed_job[2] == "canceled":
                _update_item(item_id, "canceled", "Canceled by requester")
                continue

            try:
                if dry_run:
                    _update_item(item_id, "completed", None)
                    update_progress(job_id, "completed")
                    continue

                token = site.tokens["rollback"]

                site.simple_request(
                    action="rollback",
                    title=file_title,
                    user=target_user,
                    token=token,
                    summary=summary
                    or f"Mass rollback via bucksaltbot queue; requested-by={requested_by}",
                    markbot=1,
                    bot=1,
                ).submit()

                _update_item(item_id, "completed", None)
                update_progress(job_id, "completed")

                # Track flagged-bot accounts for post-batch notification.
                if site and status_updater.is_flagged_bot(site, target_user):
                    notified_bots[target_user] = notified_bots.get(target_user, 0) + 1

            except Exception as exc:  # noqa: BLE001
                failed += 1
                _update_item(item_id, "failed", str(exc))
                update_progress(job_id, "failed")

        # Notify each flagged-bot account that was rolled back (once per job).
        if site:
            for bot_user, count in notified_bots.items():
                status_updater.notify_bot_user(site, bot_user, batch_id, edit_count=count)

        # AFTER the loop finishes
        final_status = "failed" if failed else "completed"
        set_progress(
            job_id,
            {
                "status": final_status,
                "total": len(items),
                "completed": len(items) - failed,
                "failed": failed,
            },
        )

        _update_job_status(job_id, final_status)

        status_updater.update_wiki_status(
            editing="Idle",
            last_job=f"{'Failed' if failed else 'Completed'} batch {batch_id} (job {job_id})",
            details=f"{len(items) - failed}/{len(items)} items completed",
        )

    except Exception as exc:
        job, items = _fetch_job(job_id)

        if items:
            for item_id, *_ in items:
                _update_item(item_id, "failed", str(exc))
                update_progress(job_id, "failed")

        _update_job_status(job_id, "failed")

        status_updater.update_wiki_status(
            editing="Error",
            details=str(exc)[:200],
        )

        raise
