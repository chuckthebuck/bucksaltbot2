import threading
from datetime import datetime, timezone

from self_delete.models import Candidate, Inspection
from self_delete.service import run_self_delete


class Config(dict):
    def as_dict(self):
        return dict(self)


class Logger:
    def __init__(self):
        self.messages = []

    def log(self, message):
        self.messages.append(message)


class Context:
    run_id = 77

    def __init__(self, config):
        self.config = Config(config)
        self.logger = Logger()

    def check_cancelled(self):
        return None


class Audit:
    def __init__(self):
        self.statuses = {}
        self.events = []
        self.finished = None

    def create_run(self, **_kwargs):
        return 9

    def add_candidate(self, _run_id, candidate):
        return {"File:A.jpg": 1, "File:B.jpg": 2}[candidate.title]

    def event(self, *args):
        self.events.append(args)

    def inspection(self, _run_id, candidate_id, result, *, phase):
        self.events.append((phase, candidate_id, result.reason_code))

    def set_candidate_status(self, _run_id, candidate_id, status, code, detail):
        self.statuses[candidate_id] = (status, code, detail)

    def finish_run(self, run_id, **values):
        self.finished = (run_id, values)

    def mark_run_queued(self, run_id, **values):
        self.finished = (run_id, {"status": "queued", **values})


class Gateway:
    def __init__(self, *, become_used=False):
        self.become_used = become_used
        self.inspections = 0
        self.deleted = []
        self.thread_names = []

    def discover(self, _category, _limit):
        return [Candidate("File:A.jpg", 1), Candidate("File:B.jpg", 2)]

    def inspect(self, candidate, **_kwargs):
        self.inspections += 1
        self.thread_names.append(threading.current_thread().name)
        eligible = candidate.title == "File:A.jpg"
        code = "eligible" if eligible else "not_autopatrolled"
        if (
            self.become_used
            and candidate.title == "File:A.jpg"
            and self.inspections > 1
        ):
            eligible, code = False, "in_use"
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


def test_dry_run_parallel_inspection_never_deletes():
    audit = Audit()
    gateways = []
    queued = {}

    def factory():
        gateway = Gateway()
        gateways.append(gateway)
        return gateway

    def submitter(**values):
        queued.update(values)
        return {"job_ids": [101], "batch_id": 55, "chunks": 1, "total_items": 1}

    result = run_self_delete(
        Context({"dry_run": True, "workers": 2}),
        audit_store=audit,
        gateway_factory=factory,
        queue_submitter=submitter,
    )

    assert result["status"] == "queued"
    assert result["eligible"] == 1
    assert result["skipped"] == 1
    assert result["deleted"] == 0
    assert queued["settings"].dry_run is True
    assert queued["candidates"][0].title == "File:A.jpg"
    assert all(not gateway.deleted for gateway in gateways)
    assert any(
        name.startswith("self-delete-check")
        for gateway in gateways
        for name in gateway.thread_names
    )


def test_payload_cannot_disable_configured_dry_run():
    audit = Audit()
    gateway = Gateway()

    result = run_self_delete(
        Context({"dry_run": True, "workers": 1}),
        {"dry_run": False},
        audit_store=audit,
        gateway_factory=lambda: gateway,
        queue_submitter=lambda **_values: {
            "job_ids": [101],
            "batch_id": 55,
            "chunks": 1,
            "total_items": 1,
        },
    )

    assert result["dry_run"] is True
    assert gateway.deleted == []


def test_payload_can_force_live_configuration_into_dry_run():
    """A manual test remains safe if global configuration changes after enqueue."""
    audit = Audit()
    queued = {}

    def submitter(**values):
        queued.update(values)
        return {"job_ids": [102], "batch_id": 56, "chunks": 1, "total_items": 1}

    result = run_self_delete(
        Context({"dry_run": False, "workers": 1}),
        {"dry_run": True, "source": "self_delete_ui_dry_run"},
        audit_store=audit,
        gateway_factory=Gateway,
        queue_submitter=submitter,
    )

    assert result["dry_run"] is True
    assert queued["settings"].dry_run is True


def test_live_run_hands_eligible_file_to_queue_instead_of_deleting_inline():
    audit = Audit()
    shared = Gateway()
    queued = {}

    def submitter(**values):
        queued.update(values)
        return {"job_ids": [202], "batch_id": 66, "chunks": 1, "total_items": 1}

    result = run_self_delete(
        Context({"dry_run": False, "workers": 1}),
        audit_store=audit,
        gateway_factory=lambda: shared,
        queue_submitter=submitter,
    )

    assert result["status"] == "queued"
    assert result["deleted"] == 0
    assert result["skipped"] == 1
    assert shared.deleted == []
    assert queued["settings"].dry_run is False
