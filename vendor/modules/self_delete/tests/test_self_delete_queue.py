import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from self_delete.models import Candidate, Inspection
from self_delete.queue import (
    enqueue_self_delete_batch,
    process_queued_self_delete,
    process_self_delete_job,
)


class WorkerAudit:
    def __init__(self):
        self.events = []
        self.statuses = {}

    def event(self, *args):
        self.events.append(args)

    def inspection(self, _run_id, candidate_id, result, *, phase):
        self.events.append((phase, candidate_id, result.reason_code))

    def set_candidate_status(self, _run_id, candidate_id, status, code, detail):
        self.statuses[candidate_id] = (status, code, detail)

    def refresh_run(self, run_id):
        self.events.append(("refresh", run_id))
        return {"status": "completed", "pending": 0}


class Gateway:
    def __init__(self, *, become_used=False):
        self.become_used = become_used
        self.inspections = 0
        self.deleted = []

    def inspect(self, candidate, **_kwargs):
        self.inspections += 1
        eligible = not (self.become_used and self.inspections > 1)
        code = "eligible" if eligible else "in_use"
        return Inspection(
            candidate,
            eligible,
            code,
            code,
            "Alice",
            "Alice",
            datetime.now(timezone.utc),
            {"eligible": eligible},
        )

    def delete(self, title, _reason):
        self.deleted.append(title)
        return {"delete": {"title": title}}


def payload():
    return json.dumps(
        {
            "audit_run_id": 9,
            "audit_candidate_id": 1,
            "page_id": 1,
            "max_age_seconds": 604800,
            "deletion_reason": "G7 test",
        }
    )


def test_queue_worker_revalidates_and_skips_file_that_becomes_used():
    audit = WorkerAudit()
    gateway = Gateway(become_used=True)
    gateway.inspections = 1

    with (
        patch("self_delete.queue.SQLAuditStore", return_value=audit),
        patch("self_delete.queue.CommonsGateway", return_value=gateway),
    ):
        detail = process_queued_self_delete(
            site=object(), title="File:A.jpg", payload_json=payload(), dry_run=False
        )

    assert detail.startswith("Skipped after queue recheck")
    assert gateway.deleted == []
    assert audit.statuses[1][1] == "queue_recheck_in_use"


def test_queue_worker_dry_run_revalidates_without_deleting():
    audit = WorkerAudit()
    gateway = Gateway()

    with (
        patch("self_delete.queue.SQLAuditStore", return_value=audit),
        patch("self_delete.queue.CommonsGateway", return_value=gateway),
    ):
        detail = process_queued_self_delete(
            site=object(), title="File:A.jpg", payload_json=payload(), dry_run=True
        )

    assert "dry-run" in detail
    assert gateway.deleted == []
    assert audit.statuses[1][0] == "dry_run"


def test_enqueue_uses_dedicated_tables_and_dispatches_worker_chunks():
    cursor = MagicMock()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    connection.cursor.return_value.__exit__.return_value = False
    job_ids = iter((101, 102))

    def execute(statement, _params):
        if "INSERT INTO self_delete_jobs" in statement:
            cursor.lastrowid = next(job_ids)

    cursor.execute.side_effect = execute
    candidates = [Candidate("File:A.jpg", 1), Candidate("File:B.jpg", 2)]
    settings = SimpleNamespace(
        workers=2,
        dry_run=True,
        max_age_seconds=604800,
        deletion_reason="G7 test",
    )
    task = MagicMock()

    with (
        patch("self_delete.queue._open_conn", return_value=connection),
        patch("self_delete.schema.init_schema"),
        patch("self_delete.queue.process_self_delete_job", task),
    ):
        result = enqueue_self_delete_batch(
            settings=settings,
            run_id=9,
            candidates=candidates,
            candidate_ids={"File:A.jpg": 1, "File:B.jpg": 2},
            inspections={
                "File:A.jpg": SimpleNamespace(uploader="Alice"),
                "File:B.jpg": SimpleNamespace(uploader="Bob"),
            },
        )

    assert result["job_ids"] == [101, 102]
    assert result["chunks"] == 2
    assert task.delay.call_args_list == [call(101), call(102)]
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert (
        sum("INSERT INTO self_delete_jobs" in statement for statement in statements)
        == 2
    )
    assert (
        sum(
            "INSERT INTO self_delete_job_items" in statement for statement in statements
        )
        == 2
    )


def test_dedicated_worker_claims_and_completes_own_table_item():
    job = (101, 9, "queued", 1, 55)
    claimed = (501, 101, "File:A.jpg", payload())
    site = object()

    with (
        patch("self_delete.queue._fetch_job", side_effect=[job, job]),
        patch(
            "self_delete.queue.claim_next_self_delete_item",
            side_effect=[claimed, None],
        ),
        patch("self_delete.queue._update_job_status") as update_job,
        patch("self_delete.queue._update_item") as update_item,
        patch("self_delete.queue._reconcile_job") as reconcile,
        patch("self_delete.queue._bot_site", return_value=site),
        patch("self_delete.schema.init_schema"),
        patch(
            "self_delete.queue.process_queued_self_delete",
            return_value="Eligible; dry-run",
        ) as process_item,
    ):
        process_self_delete_job.run(101)

    process_item.assert_called_once_with(
        site=site,
        title="File:A.jpg",
        payload_json=claimed[3],
        dry_run=True,
    )
    update_item.assert_called_once_with(501, "completed", "Eligible; dry-run")
    assert update_job.call_args_list[0] == call(101, "running")
    assert reconcile.call_args_list[-1] == call(101)
