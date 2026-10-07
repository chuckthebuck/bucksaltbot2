from datetime import datetime, timedelta, timezone

from self_delete.models import Candidate
from self_delete.wiki import CommonsGateway

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


class Request:
    def __init__(self, response):
        self.response = response

    def submit(self):
        return self.response


class Site:
    def __init__(self, page, *, rights=("autopatrol",)):
        self.page = page
        self.rights = list(rights)
        self.tokens = {"csrf": "TOKEN"}
        self.calls = []

    def simple_request(self, **params):
        self.calls.append(params)
        if params.get("list") == "users":
            return Request({"query": {"users": [{"rights": self.rights}]}})
        if params.get("action") == "delete":
            return Request({"delete": {"title": params["title"]}})
        if params.get("action") == "edit":
            return Request({"edit": {"title": params["title"], "result": "Success"}})
        return Request({"query": {"pages": [self.page]}})


def page(*, request_user="Alice", uploader="Alice", age_days=1, usage=False):
    upload_time = NOW - timedelta(days=age_days)
    return {
        "pageid": 10,
        "ns": 6,
        "title": "File:Example.jpg",
        "revisions": [
            {
                "timestamp": upload_time.isoformat(),
                "user": uploader,
                "slots": {"main": {"content": "description"}},
            },
            {
                "timestamp": (upload_time + timedelta(hours=1)).isoformat(),
                "user": request_user,
                "slots": {"main": {"content": "{{SD|G7}}\ndescription"}},
            },
        ],
        "imageinfo": [{"timestamp": upload_time.isoformat(), "user": uploader}],
        "imageusage": [{"title": "Used"}] if usage else [],
        "globalusage": [],
    }


def inspect(site):
    return CommonsGateway(site).inspect(
        Candidate("File:Example.jpg", 10), now=NOW, max_age_seconds=604800
    )


def test_eligible_g7_request_passes_all_checks():
    result = inspect(Site(page()))

    assert result.eligible is True
    assert result.reason_code == "eligible"
    assert result.checks["requester_is_uploader"] is True
    assert result.checks["uploader_has_autopatrol"] is True


def test_speedydelete_and_speedy_shortcut_with_g7_are_recognized():
    for marker in (
        "{{Speedydelete|G7: uploader request}}",
        "{{speedy|reason=G7}}",
        "{{Template:SD | 1 = g7 }}",
        "{{speedy_delete|G7}}",
    ):
        snapshot = page()
        snapshot["revisions"][-1]["slots"]["main"]["content"] = marker

        result = inspect(Site(snapshot))

        assert result.eligible is True, marker


def test_g7_must_be_an_active_speedy_template_parameter():
    for text in (
        "G7 mentioned in prose only",
        "{{Delete|G7}}",
        "{{G7}}",
        "{{SD|G70}}",
        "<!-- {{SD|G7}} -->",
        "{{SD|G7(failed bot)}}",
    ):
        snapshot = page()
        snapshot["revisions"][-1]["slots"]["main"]["content"] = text

        result = inspect(Site(snapshot))

        assert result.eligible is False, text
        assert result.reason_code == "missing_g7", text


def test_missing_revision_history_is_unverifiable_and_skipped():
    snapshot = page()
    snapshot["revisions"] = []

    result = inspect(Site(snapshot))

    assert result.eligible is False
    assert result.reason_code == "missing_g7"


def test_request_must_be_made_by_original_uploader():
    result = inspect(Site(page(request_user="Mallory")))

    assert result.eligible is False
    assert result.reason_code == "requester_not_uploader"


def test_file_must_be_strictly_younger_than_seven_days():
    result = inspect(Site(page(age_days=7)))

    assert result.eligible is False
    assert result.reason_code == "too_old"


def test_used_file_is_rejected():
    result = inspect(Site(page(usage=True)))

    assert result.eligible is False
    assert result.reason_code == "in_use"


def test_uploader_must_currently_have_autopatrol_right():
    result = inspect(Site(page(), rights=()))

    assert result.eligible is False
    assert result.reason_code == "not_autopatrolled"


def test_delete_uses_csrf_token_and_reason():
    site = Site(page())
    response = CommonsGateway(site).delete("File:Example.jpg", "G7 test")

    assert response["delete"]["title"] == "File:Example.jpg"
    assert site.calls[-1]["token"] == "TOKEN"
    assert site.calls[-1]["reason"] == "G7 test"


def test_failed_g7_is_rewritten_for_other_speedy_deletions():
    snapshot = page()
    snapshot["revisions"][-1]["revid"] = 123
    site = Site(snapshot)

    response = CommonsGateway(site).route_failed_g7(
        "File:Example.jpg", "not_autopatrolled"
    )

    assert response["edit"]["result"] == "Success"
    request = site.calls[-1]
    assert request["action"] == "edit"
    assert "{{SD|G7(failed bot)}}" in request["text"]
    assert request["baserevid"] == 123
    assert "not_autopatrolled" in request["summary"]
    assert request["token"] == "TOKEN"
