from dataclasses import dataclass

import pytest

from chuck_salt_shack.codegen import render_jobs_py
from chuck_salt_shack.service import execute_workflow, run_saltlick
from chuck_salt_shack.spec import WorkflowSpec


def recipe():
    return {
        "version": 1,
        "name": "Example bot",
        "wiki": {"code": "commons", "family": "commons"},
        "source": {
            "type": "titles",
            "titles": ["User:Example/Sandbox"],
            "limit": 10,
        },
        "filters": {
            "skip_redirects": True,
            "skip_missing": True,
        },
        "transforms": [
            {"type": "literal_replace", "find": "old", "replace": "new"},
            {"type": "append", "text": "\nUpdated {{title}}"},
        ],
        "save": {
            "summary": "Updating {{pagename}}",
            "minor": True,
            "bot": True,
            "watch": "nochange",
        },
        "limits": {"max_edits": 10, "stop_on_error": False},
    }


@dataclass
class FakePage:
    page_title: str
    text: str
    exists_value: bool = True
    redirect: bool = False

    def __post_init__(self):
        self.save_calls = []

    def title(self):
        return self.page_title

    def namespace(self):
        return 2 if self.page_title.startswith("User:") else 0

    def exists(self):
        return self.exists_value

    def isRedirectPage(self):
        return self.redirect

    def save(self, **kwargs):
        self.save_calls.append(kwargs)


class FakeContext:
    def __init__(self, page, *, job_name="preview", config=None):
        self.job_name = job_name
        self.config = config or {}
        self.page = page
        self.cancel_checks = 0

    def check_cancelled(self):
        self.cancel_checks += 1

    def site(self, code, family):
        assert code == "commons"
        assert family == "commons"
        return object()


def test_dry_run_records_diff_without_saving():
    page = FakePage("User:Example/Sandbox", "old value")

    result = execute_workflow(
        object(),
        recipe(),
        dry_run=True,
        pages=[page],
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["changed_count"] == 1
    assert result["saved_count"] == 0
    assert page.save_calls == []
    assert "-old value" in result["items"][0]["diff"]
    assert "+new value" in result["items"][0]["diff"]
    assert result["dry_run_edits"][0]["status"] == "proposed"


def test_live_run_saves_with_reviewed_options():
    page = FakePage("User:Example/Sandbox", "old value")

    result = execute_workflow(
        object(),
        recipe(),
        dry_run=False,
        pages=[page],
        sleep=lambda _seconds: None,
    )

    assert result["saved_count"] == 1
    assert page.text == "new value\nUpdated User:Example/Sandbox"
    assert page.save_calls == [
        {
            "summary": "Updating Example/Sandbox",
            "minor": True,
            "botflag": True,
            "watch": "nochange",
        }
    ]


def test_filters_skip_redirects_and_missing_pages():
    pages = [
        FakePage("Redirect", "old", redirect=True),
        FakePage("Missing", "", exists_value=False),
    ]

    result = execute_workflow(object(), recipe(), dry_run=True, pages=pages)

    assert result["changed_count"] == 0
    assert result["skipped_count"] == 2
    assert [item["reason"] for item in result["items"]] == ["redirect", "missing"]


def test_preview_handler_cannot_be_switched_live_by_payload(monkeypatch):
    page = FakePage("User:Example/Sandbox", "old")
    ctx = FakeContext(page, job_name="preview")

    monkeypatch.setattr(
        "chuck_salt_shack.service.resolve_pages",
        lambda _site, _source: [page],
    )
    result = run_saltlick(
        ctx,
        {"recipe": recipe(), "confirm_live": True},
    )

    assert result["dry_run"] is True
    assert page.save_calls == []


def test_apply_handler_requires_confirmation():
    page = FakePage("User:Example/Sandbox", "old")
    ctx = FakeContext(page, job_name="apply")

    with pytest.raises(ValueError, match="confirm_live"):
        run_saltlick(ctx, {"recipe": recipe()})


def test_handler_rejects_script_payload_even_through_generic_run_api():
    page = FakePage("User:Example/Sandbox", "old")
    ctx = FakeContext(page, job_name="preview")

    with pytest.raises(ValueError, match="unsupported run argument"):
        run_saltlick(
            ctx,
            {
                "recipe": recipe(),
                "script": "print('not accepted')",
            },
        )


def test_safe_mode_forces_apply_handler_back_to_dry_run(monkeypatch):
    page = FakePage("User:Example/Sandbox", "old")
    ctx = FakeContext(page, job_name="apply", config={"dry_run": True})
    monkeypatch.setattr(
        "chuck_salt_shack.service.resolve_pages",
        lambda _site, _source: [page],
    )

    result = run_saltlick(
        ctx,
        {"recipe": recipe(), "confirm_live": True},
    )

    assert result["dry_run"] is True
    assert page.save_calls == []


def test_generated_handler_is_valid_python_and_preserves_recipe():
    import ast

    workflow = WorkflowSpec.from_dict(recipe())
    generated = render_jobs_py(workflow)

    ast.parse(generated)
    assert '"Example bot"' in generated
    assert "confirm_live" in generated
