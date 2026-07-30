"""Tests for the safe generated-job block updater."""

from scripts.update_generated_jobs_yaml import replace_generated_block


def test_replace_generated_block_preserves_static_jobs():
    jobs = """- name: celery
# BEGIN GENERATED MODULE JOBS
- name: old-module-job
# END GENERATED MODULE JOBS
- name: status
"""

    updated = replace_generated_block(jobs, "- name: fresh-module-job\n  schedule: '* * * * *'")

    assert "- name: celery" in updated
    assert "- name: status" in updated
    assert "old-module-job" not in updated
    assert "fresh-module-job" in updated


def test_replace_generated_block_rejects_missing_markers():
    try:
        replace_generated_block("- name: celery\n", "- name: module\n")
    except ValueError as exc:
        assert "marker pair" in str(exc)
    else:
        raise AssertionError("missing marker pair should fail")
