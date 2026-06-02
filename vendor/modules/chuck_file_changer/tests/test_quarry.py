from chuck_file_changer.quarry import (
    parse_targets_text,
    quarry_result_url,
)


def test_quarry_result_url_accepts_query_url():
    assert (
        quarry_result_url("https://quarry.wmcloud.org/query/12345")
        == "https://quarry.wmcloud.org/query/12345/result/latest/0/json"
    )


def test_quarry_result_url_accepts_run_id():
    assert (
        quarry_result_url("run:99")
        == "https://quarry.wmcloud.org/run/99/output/0/json"
    )


def test_parse_quarry_json_rows():
    targets = parse_targets_text(
        '{"headers":["img_name","actor_name","comment_text"],'
        '"rows":[["Example.jpg","Uploader","note"]]}'
    )

    assert targets[0].title == "File:Example.jpg"
    assert targets[0].user == "Uploader"
    assert targets[0].summary_hint == "note"


def test_parse_csv_targets_dedupes_titles():
    targets = parse_targets_text(
        "file_title,target_user\nFile:One.jpg,Alice\nOne.jpg,Bob\nTwo.jpg,Bob"
    )

    assert [target.title for target in targets] == ["File:One.jpg", "File:Two.jpg"]


def test_parse_manual_targets():
    targets = parse_targets_text("One.jpg|Alice|note\nFile:Two.jpg")

    assert targets[0].title == "File:One.jpg"
    assert targets[0].user == "Alice"
    assert targets[0].summary_hint == "note"
    assert targets[1].title == "File:Two.jpg"
