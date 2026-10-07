"""Offline harness coverage proves fixtures cannot perform deletions."""

from pathlib import Path

from self_delete.harness import FixtureSite, load_fixture, main, run_fixture

FIXTURE = Path(__file__).parent / "fixtures" / "dry_run_mixed.json"


def test_mixed_fixture_reports_eligible_and_skipped_without_deleting():
    """The harness exercises real policy checks while remaining read-only."""
    result = run_fixture(load_fixture(FIXTURE))

    assert result["mode"] == "dry_run"
    assert result["discovered"] == 2
    assert result["eligible"] == 1
    assert result["skipped"] == 1
    assert result["delete_attempts"] == []
    assert [item["reason_code"] for item in result["decisions"]] == [
        "eligible",
        "in_use",
    ]


def test_fixture_site_rejects_delete_requests():
    """Even accidental future calls to delete fail closed in the harness."""
    site = FixtureSite(load_fixture(FIXTURE))

    try:
        site.simple_request(action="delete", title="File:Eligible example.jpg")
    except AssertionError as exc:
        assert "cannot delete" in str(exc)
    else:
        raise AssertionError("Fixture harness unexpectedly accepted a delete request")


def test_harness_cli_prints_json(capsys):
    """The module-level CLI is convenient for local operator smoke tests."""
    assert main([str(FIXTURE), "--compact"]) == 0

    output = capsys.readouterr().out
    assert '"mode": "dry_run"' in output
