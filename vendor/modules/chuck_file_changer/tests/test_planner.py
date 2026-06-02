from chuck_file_changer.models import FileChangeOperation, FileChangeTarget
from chuck_file_changer.planner import apply_operation, plan_target


def test_replace_operation_changes_text():
    operation = FileChangeOperation(mode="replace", find="old", replace="new")

    assert apply_operation("old text", operation) == "new text"


def test_plan_target_reports_unchanged_when_find_is_missing():
    target = FileChangeTarget(title="File:One.jpg")
    operation = FileChangeOperation(mode="replace", find="missing", replace="new")

    item = plan_target(target, operation, "old text")

    assert item.status == "unchanged"
    assert not item.changed


def test_plan_target_includes_diff_for_change():
    target = FileChangeTarget(title="File:One.jpg")
    operation = FileChangeOperation(mode="append", append="new")

    item = plan_target(target, operation, "old\n")

    assert item.status == "changed"
    assert "File:One.jpg (before)" in item.diff
    assert "+new" in item.diff
