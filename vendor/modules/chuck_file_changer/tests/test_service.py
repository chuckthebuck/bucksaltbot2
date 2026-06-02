from chuck_file_changer.service import run_file_change
from chuck_file_changer.config import DEFAULT_USER_AGENT


class FakeWiki:
    def __init__(self):
        self.pages = {"File:One.jpg": "old text"}
        self.saved = []

    def get_text(self, title):
        return self.pages[title]

    def save_text(self, title, text, summary):
        self.saved.append((title, text, summary))


def test_run_file_change_defaults_to_dry_run():
    wiki = FakeWiki()

    result = run_file_change(
        payload={
            "source_text": "One.jpg",
            "mode": "replace",
            "find": "old",
            "replace": "new",
            "wiki_client": wiki,
        }
    )

    assert result["dry_run"] is True
    assert result["changed_count"] == 1
    assert result["saved_count"] == 0
    assert wiki.saved == []


def test_run_file_change_saves_when_apply_and_not_dry_run():
    wiki = FakeWiki()

    result = run_file_change(
        payload={
            "source_text": "One.jpg",
            "mode": "replace",
            "find": "old",
            "replace": "new",
            "apply": True,
            "dry_run": False,
            "wiki_client": wiki,
        }
    )

    assert result["dry_run"] is False
    assert result["saved_count"] == 1
    assert wiki.saved[0][0] == "File:One.jpg"
    assert wiki.saved[0][1] == "new text"


def test_run_file_change_checks_cancellation_between_targets():
    wiki = FakeWiki()
    wiki.pages["File:Two.jpg"] = "old text"

    class Context:
        def __init__(self):
            self.checks = 0

        def check_cancelled(self):
            self.checks += 1
            if self.checks == 2:
                raise RuntimeError("stopped")

    ctx = Context()

    try:
        run_file_change(
            ctx,
            {
                "source_text": "One.jpg\nTwo.jpg",
                "mode": "replace",
                "find": "old",
                "replace": "new",
                "wiki_client": wiki,
            },
        )
    except RuntimeError as exc:
        assert str(exc) == "stopped"
    else:
        raise AssertionError("expected cancellation exception")

    assert ctx.checks == 2


def test_quarry_fetch_uses_module_user_agent(monkeypatch):
    import chuck_file_changer.service as service

    class Response:
        text = '{"headers":["img_name"],"rows":[["One.jpg"]]}'

        def raise_for_status(self):
            return None

    calls = []

    def fake_get(url, *, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return Response()

    monkeypatch.setattr(service.requests, "get", fake_get)

    targets, source_url = service.targets_from_payload({"quarry": "123"})

    assert source_url == "https://quarry.wmcloud.org/query/123/result/latest/0/json"
    assert targets[0].title == "File:One.jpg"
    assert calls[0]["headers"]["User-Agent"] == DEFAULT_USER_AGENT
