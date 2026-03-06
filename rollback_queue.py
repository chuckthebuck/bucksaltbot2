import os
from celery import shared_task
import pywikibot

from toolsdb import get_conn


def _fetch_job(job_id: int):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, requested_by, status, dry_run FROM rollback_jobs WHERE id=%s",
                (job_id,),
            )
            job = cursor.fetchone()
            if not job:
                return None, []
            cursor.execute(
                "SELECT id, file_title, target_user, summary FROM rollback_job_items WHERE job_id=%s ORDER BY id ASC",
                (job_id,),
            )
            items = cursor.fetchall()
    return job, items


def _update_job_status(job_id: int, status: str):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE rollback_jobs SET status=%s WHERE id=%s", (status, job_id))
        conn.commit()


def _update_item(item_id: int, status: str, error: str | None = None):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE rollback_job_items SET status=%s, error=%s WHERE id=%s",
                (status, error, item_id),
            )
        conn.commit()


def _bot_site() -> pywikibot.Site:
    username = os.environ.get("BOT_USERNAME")
    password = os.environ.get("BOT_PASSWORD")
    if not username or not password:
        raise RuntimeError("BOT_USERNAME and BOT_PASSWORD must be configured")
    site = pywikibot.Site("commons", "commons")
    site.login(user=username, password=password)
    return site


@shared_task(ignore_result=True)
def process_rollback_job(job_id: int):
    job, items = _fetch_job(job_id)
    if not job:
        return

    _update_job_status(job_id, "running")
    _, requested_by, _, dry_run = job

    site = None
    if not dry_run:
        site = _bot_site()

    failed = 0
    for item_id, file_title, target_user, summary in items:
        try:
            if dry_run:
                _update_item(item_id, "completed", None)
                continue

            token = site.tokens["rollback"]
            site.simple_request(
                action="rollback",
                title=file_title,
                user=target_user,
                token=token,
                summary=summary or f"Mass rollback via bucksaltbot queue; requested-by={requested_by}",
                markbot=1,
                bot=1,
            ).submit()
            _update_item(item_id, "completed", None)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            _update_item(item_id, "failed", str(exc))

    _update_job_status(job_id, "failed" if failed else "completed")
