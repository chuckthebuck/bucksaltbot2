import pywikibot

from router.wiki_actions import execute_action_plan


def action():
    return {
        "type": "mediawiki.page.purge",
        "target": {
            "wiki": {"code": "commons", "family": "commons"},
            "namespace": 0,
            "title": "Main Page",
        },
        "params": {"forcelinkupdate": True},
    }


def test_dry_run_does_not_create_a_site():
    calls = []

    result = execute_action_plan(
        [action()],
        site_factory=lambda code, family: calls.append((code, family)),
        dry_run=True,
        allowed_types=["mediawiki.page.purge"],
    )

    assert result["ok"] is True
    assert result["planned_count"] == 1
    assert result["completed_count"] == 0
    assert result["items"][0]["status"] == "planned"
    assert calls == []


def test_live_purge_uses_framework_reviewed_request(monkeypatch):
    submitted = []

    class FakeRequest:
        def __init__(self, params):
            self.params = params

        def submit(self):
            submitted.append(self.params)
            return {"purge": [{"title": "Main Page", "purged": ""}]}

    class FakeSite:
        def simple_request(self, **params):
            return FakeRequest(params)

    class FakePage:
        def __init__(self, _site, title, ns=0):
            self._title = title
            self._namespace = ns

        def title(self):
            return self._title

    monkeypatch.setattr(pywikibot, "Page", FakePage)

    result = execute_action_plan(
        [action()],
        site_factory=lambda _code, _family: FakeSite(),
        dry_run=False,
        allowed_types=["mediawiki.page.purge"],
    )

    assert result["ok"] is True
    assert result["completed_count"] == 1
    assert submitted == [
        {
            "action": "purge",
            "titles": "Main Page",
            "forcelinkupdate": 1,
        }
    ]
