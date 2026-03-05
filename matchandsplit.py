from celery import shared_task

from app import celery as celery_app
from logger import Logger
from toolsdb import get_conn

MATCH_AND_SPLIT_REMOVED_MSG = (
    "Legacy match/split edit functionality has been removed to prevent buggy mass edits."
)


def _set_legacy_job_status(job_id: str, lang: str, title: str, username: str, job_type: str, status: str, log_file: str | None = None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cursor:
            if log_file is None:
                cursor.execute(
                    """UPDATE jobs
                       SET status = %s
                       WHERE id = %s AND type = %s AND lang = %s AND title = %s AND username = %s""",
                    (status, job_id, job_type, lang, title, username),
                )
            else:
                cursor.execute(
                    """UPDATE jobs
                       SET status = %s, logfile = %s
                       WHERE id = %s AND type = %s AND lang = %s AND title = %s AND username = %s""",
                    (status, log_file, job_id, job_type, lang, title, username),
                )
        conn.commit()


@shared_task
def match(lang, title, username, log_file, jid) -> None:
    logger = Logger(log_file)
    logger.log(MATCH_AND_SPLIT_REMOVED_MSG)
    _set_legacy_job_status(str(jid), lang, title, username, "match", "running", log_file=log_file)
    _set_legacy_job_status(str(jid), lang, title, username, "match", "done")


@shared_task
def split(lang, title, username, log_file, jid) -> None:
    logger = Logger(log_file)
    logger.log(MATCH_AND_SPLIT_REMOVED_MSG)
    _set_legacy_job_status(str(jid), lang, title, username, "split", "running", log_file=log_file)
    _set_legacy_job_status(str(jid), lang, title, username, "split", "done")
