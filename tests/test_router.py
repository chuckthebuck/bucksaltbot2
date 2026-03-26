"""Tests for router.py – rollback API and UI routes."""

from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_mock_conn(cursor=None):
    """Return a (mock_conn, mock_cursor) suitable for patching get_conn()."""
    mock_cursor = cursor or MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


def _set_session(client, username):
    with client.session_transaction() as sess:
        sess["username"] = username


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def flask_app():
    import router

    router.app.config["TESTING"] = True
    router.app.config["SECRET_KEY"] = "test-secret"
    return router.app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()


# ── POST /api/v1/rollback/jobs ────────────────────────────────────────────────


def test_create_job_returns_401_when_not_authenticated(client):
    resp = client.post(
        "/api/v1/rollback/jobs", json={"requested_by": "user", "items": []}
    )
    assert resp.status_code == 401


def test_create_job_returns_403_when_requester_mismatches_session(client):
    _set_session(client, "alice")
    mock_conn, _ = _make_mock_conn()
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.process_rollback_job") as mock_task,
    ):
        mock_task.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": "bob",
                "items": [{"title": "File:T.jpg", "user": "V"}],
            },
        )
    assert resp.status_code == 403


def test_create_job_returns_400_when_items_empty(client):
    _set_session(client, "alice")
    mock_conn, _ = _make_mock_conn()
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={"requested_by": "alice", "items": []},
        )
    assert resp.status_code == 400


def test_create_job_success_returns_job_id_and_queued_status(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.lastrowid = 99
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.process_rollback_job") as mock_task,
    ):
        mock_task.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": "alice",
                "items": [{"title": "File:Test.jpg", "user": "Vandal"}],
            },
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["job_id"] == 99
    assert data["status"] == "queued"


def test_create_job_enqueues_celery_task_with_job_id(client):
    """create_rollback_job must call process_rollback_job.delay(job_id)."""
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.lastrowid = 7
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.process_rollback_job") as mock_task,
    ):
        mock_task.delay = MagicMock()
        client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": "alice",
                "items": [{"title": "File:Test.jpg", "user": "Vandal"}],
            },
        )
    mock_task.delay.assert_called_once_with(7)


def test_create_job_dry_run_flag_persisted(client):
    """dry_run=True is recorded and the task is still enqueued."""
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.lastrowid = 5
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.process_rollback_job") as mock_task,
    ):
        mock_task.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": "alice",
                "dry_run": True,
                "items": [{"title": "File:Test.jpg", "user": "Vandal"}],
            },
        )
    assert resp.status_code == 200
    # Verify the INSERT used dry_run=1
    insert_args = mock_cursor.execute.call_args_list[0]
    assert 1 in insert_args.args[1]  # dry_run value is 1


def test_create_job_dry_run_string_false_persisted_as_zero(client):
    """dry_run='false' should be interpreted as False and stored as 0."""
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.lastrowid = 6
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.process_rollback_job") as mock_task,
    ):
        mock_task.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": "alice",
                "dry_run": "false",
                "items": [{"title": "File:Test.jpg", "user": "Vandal"}],
            },
        )
    assert resp.status_code == 200
    insert_args = mock_cursor.execute.call_args_list[0]
    assert insert_args.args[1][2] == 0


def test_create_job_dry_run_string_true_persisted_as_one(client):
    """dry_run='true' should be interpreted as True and stored as 1."""
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.lastrowid = 6
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.process_rollback_job") as mock_task,
    ):
        mock_task.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": "alice",
                "dry_run": "true",
                "items": [{"title": "File:Test.jpg", "user": "Vandal"}],
            },
        )
    assert resp.status_code == 200
    insert_args = mock_cursor.execute.call_args_list[0]
    assert insert_args.args[1][2] == 1


def test_create_job_uses_client_batch_id_when_provided(client):
    """batch_id allows grouping multiple POSTs under one logical batch."""
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.lastrowid = 6
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.process_rollback_job") as mock_task,
    ):
        mock_task.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": "alice",
                "batch_id": 123456789,
                "items": [{"title": "File:Test.jpg", "user": "Vandal"}],
            },
        )
    assert resp.status_code == 200
    assert resp.get_json()["batch_id"] == 123456789
    insert_args = mock_cursor.execute.call_args_list[0]
    assert insert_args.args[1][3] == 123456789


def test_create_job_rejects_invalid_batch_id(client):
    _set_session(client, "alice")
    mock_conn, _ = _make_mock_conn()
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": "alice",
                "batch_id": "not-a-number",
                "items": [{"title": "File:Test.jpg", "user": "Vandal"}],
            },
        )
    assert resp.status_code == 400
    assert "batch_id" in resp.get_json().get("detail", "")


def test_create_job_allows_status_token_auth(client):
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.lastrowid = 13
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.process_rollback_job") as mock_task,
        patch.dict(
            "router.os.environ",
            {"STATUS_API_TOKEN": "token123", "STATUS_API_USER": "statusbot"},
            clear=False,
        ),
    ):
        mock_task.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/jobs",
            headers={"X-Status-Token": "token123"},
            json={
                "items": [{"title": "File:Test.jpg", "user": "Vandal"}],
            },
        )
    assert resp.status_code == 200


def test_from_diff_api_returns_401_when_not_authenticated(client):
    resp = client.post("/api/v1/rollback/from-diff", json={"diff": 1})
    assert resp.status_code == 401


def test_from_diff_api_returns_403_for_non_maintainer(client):
    _set_session(client, "alice")
    with patch("router.is_maintainer", return_value=False):
        resp = client.post("/api/v1/rollback/from-diff", json={"diff": 1})
    assert resp.status_code == 403


def test_from_diff_api_rejects_invalid_limit(client):
    _set_session(client, "alice")
    with patch("router.is_maintainer", return_value=True):
        resp = client.post(
            "/api/v1/rollback/from-diff",
            json={"diff": 10, "limit": "bad"},
        )
    assert resp.status_code == 400
    assert "limit" in resp.get_json().get("detail", "")


def test_from_diff_api_passes_limit_to_creation_helper(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.lastrowid = 11

    with (
        patch("router.is_maintainer", return_value=True),
        patch("router.get_conn", return_value=mock_conn),
        patch("router.resolve_diff_rollback_job") as mock_resolve,
    ):
        mock_resolve.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/from-diff",
            json={"diff": 999, "limit": 25, "dry_run": True},
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["limit"] == 25
    assert data["dry_run"] is True
    assert data["diff"] == 999
    assert data["job_id"] == 11
    assert data["status"] == "resolving"
    mock_resolve.delay.assert_called_once_with(11)


def test_from_diff_api_accepts_diff_url(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.lastrowid = 11

    with (
        patch("router.is_maintainer", return_value=True),
        patch("router.get_conn", return_value=mock_conn),
        patch("router.resolve_diff_rollback_job") as mock_resolve,
    ):
        mock_resolve.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/from-diff",
            json={
                "diff": "https://commons.wikimedia.org/w/index.php?title=File:Example.jpg&oldid=123456",
                "limit": 20,
            },
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "resolving"
    assert "oldid=123456" in data["diff"]
    mock_resolve.delay.assert_called_once_with(11)


def test_fetch_contribs_after_timestamp_requests_timestamp_and_filters_strictly():
    import router

    start_ts = "2024-01-01T00:00:00Z"

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "query": {
            "usercontribs": [
                {
                    "title": "File:EqualTs.jpg",
                    "timestamp": "2024-01-01T00:00:00Z",
                },
                {
                    "title": "File:AfterTs.jpg",
                    "timestamp": "2024-01-01T00:00:01Z",
                },
            ]
        }
    }

    with patch("router.requests.get", return_value=mock_resp) as mock_get:
        results = router.fetch_contribs_after_timestamp("TargetUser", start_ts, limit=10)

    assert results == [{"title": "File:AfterTs.jpg", "user": "TargetUser"}]
    assert mock_get.call_count == 1
    assert mock_get.call_args.kwargs["params"]["ucprop"] == "ids|title|timestamp"


def test_fetch_contribs_after_timestamp_respects_limit():
    import router

    start_ts = "2024-01-01T00:00:00Z"

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "query": {
            "usercontribs": [
                {
                    "title": "File:One.jpg",
                    "timestamp": "2024-01-01T00:00:01Z",
                },
                {
                    "title": "File:Two.jpg",
                    "timestamp": "2024-01-01T00:00:02Z",
                },
            ]
        }
    }

    with patch("router.requests.get", return_value=mock_resp):
        results = router.fetch_contribs_after_timestamp("TargetUser", start_ts, limit=1)

    assert results == [{"title": "File:One.jpg", "user": "TargetUser"}]


def test_fetch_rollbackable_window_end_timestamp_uses_top_and_ucend():
    import router

    start_ts = "2024-01-01T00:00:00Z"

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "query": {
            "usercontribs": [
                {"title": "File:Latest.jpg", "timestamp": "2024-02-01T00:00:00Z"},
                {"title": "File:WindowEnd.jpg", "timestamp": "2024-01-15T00:00:00Z"},
            ]
        }
    }
    mock_resp.text = "{}"
    mock_resp.status_code = 200

    with patch("router.requests.get", return_value=mock_resp) as mock_get:
        end_ts = router.fetch_rollbackable_window_end_timestamp("TargetUser", start_ts)

    assert end_ts == "2024-01-15T00:00:00Z"
    params = mock_get.call_args.kwargs["params"]
    assert params["ucshow"] == "top"
    assert params["ucend"] == start_ts
    assert int(params["uclimit"]) <= 500


def test_fetch_rollbackable_window_end_timestamp_returns_none_when_empty():
    import router

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"query": {"usercontribs": []}}
    mock_resp.text = "{}"
    mock_resp.status_code = 200

    with patch("router.requests.get", return_value=mock_resp):
        end_ts = router.fetch_rollbackable_window_end_timestamp(
            "TargetUser", "2024-01-01T00:00:00Z"
        )

    assert end_ts is None


def test_fetch_diff_author_and_timestamp_handles_network_error():
    import router
    import requests

    with patch("router.requests.get") as mock_get:
        mock_get.side_effect = requests.Timeout("Connection timeout")
        with pytest.raises(ValueError, match="Failed to fetch revision metadata"):
            router.fetch_diff_author_and_timestamp(123456)


def test_fetch_contribs_after_timestamp_handles_network_error():
    import router
    import requests

    with patch("router.requests.get") as mock_get:
        mock_get.side_effect = requests.ConnectionError("Connection failed")
        with pytest.raises(ValueError, match="Failed to fetch user contributions"):
            router.fetch_contribs_after_timestamp("TestUser", "2024-01-01T00:00:00Z")


def test_retry_job_with_no_items_requeues_diff_resolution(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.side_effect = [("alice",), (0,)]

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router._load_diff_payload", return_value={"diff": 123}),
        patch("router.resolve_diff_rollback_job") as mock_resolve,
    ):
        mock_resolve.delay = MagicMock()
        resp = client.post("/api/v1/rollback/jobs/1/retry")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "resolving"
    mock_resolve.delay.assert_called_once_with(1)


def test_get_job_includes_diff_query_debug_metadata(client):
    import datetime as dt

    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    recent_created_at = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    mock_cursor.fetchone.return_value = (1, "alice", "resolving", 1, recent_created_at)
    mock_cursor.fetchall.return_value = []

    payload = {
        "diff": "https://commons.wikimedia.org/w/index.php?oldid=123456",
        "oldid": 123456,
        "resolved_user": "ExampleUser",
        "resolved_timestamp": "2026-03-25T03:30:00Z",
        "revision_query": {"action": "query", "prop": "revisions"},
        "contribs_query": {"action": "query", "list": "usercontribs"},
        "mw_debug": [
            {
                "kind": "revisions",
                "status_code": 200,
                "elapsed_ms": 121,
                "response_snippet": "{\"query\": ...}",
            }
        ],
    }

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router._load_diff_payload", return_value=payload),
        patch("router.r.get", return_value=None),
    ):
        resp = client.get("/api/v1/rollback/jobs/1")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "resolving"
    assert data["diff"].endswith("oldid=123456")
    assert data["oldid"] == 123456
    assert data["resolved_user"] == "ExampleUser"
    assert data["resolved_timestamp"] == "2026-03-25T03:30:00Z"
    assert data["revision_query"]["action"] == "query"
    assert data["contribs_query"]["list"] == "usercontribs"
    assert data["mw_debug"][0]["kind"] == "revisions"


def test_get_job_marks_stale_resolving_as_failed(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (30, "alice", "resolving", 1, "2020-01-01 00:00:00")
    mock_cursor.fetchall.return_value = []

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router._set_diff_error") as mock_set_error,
        patch("router._update_diff_payload") as mock_update_payload,
        patch("router.r.get", return_value=None),
    ):
        resp = client.get("/api/v1/rollback/jobs/30")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "failed"
    mock_set_error.assert_called_once()
    mock_update_payload.assert_called_once()


def test_all_jobs_json_marks_stale_resolving_as_failed(client):
    _set_session(client, "maintainer")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchall.return_value = [
        (30, "alice", "resolving", 1, "2020-01-01 00:00:00", 0, 0, 0),
    ]

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=True),
        patch("router._set_diff_error"),
        patch("router._update_diff_payload"),
    ):
        resp = client.get("/rollback-queue/all-jobs?format=json")

    assert resp.status_code == 200
    jobs = resp.get_json()["jobs"]
    assert jobs[0]["status"] == "failed"


def test_resolve_diff_rollback_job_propagates_query_payload_to_chunk_jobs():
    import router

    payload = {
        "diff": "123456",
        "summary": "test",
        "requested_by": "alice",
        "dry_run": True,
        "limit": 100,
    }

    items = [
        {"title": "File:One.jpg", "user": "TargetUser"},
        {"title": "File:Two.jpg", "user": "TargetUser"},
        {"title": "File:Three.jpg", "user": "TargetUser"},
    ]

    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (12345,)
    mock_cursor.lastrowid = 999

    with (
        patch("router._load_diff_payload", return_value=payload),
        patch("router._update_diff_payload") as mock_update_payload,
        patch("router.fetch_diff_author_and_timestamp", return_value={"user": "TargetUser", "timestamp": "2026-03-25T03:30:00Z"}),
        patch("router.fetch_rollbackable_window_end_timestamp", return_value="2026-03-25T04:00:00Z"),
        patch("router.iter_contribs_after_timestamp", return_value=iter(items)),
        patch("router.get_conn", return_value=mock_conn),
        patch("router._set_diff_error"),
        patch("router.status_updater.update_wiki_status"),
        patch("router._store_diff_payload") as mock_store_payload,
        patch("router.process_rollback_job") as mock_task,
        patch("router.MAX_JOB_ITEMS", 2),
    ):
        mock_task.delay = MagicMock()
        router.resolve_diff_rollback_job(1)

    mock_update_payload.assert_called()
    mock_store_payload.assert_called_once()
    chunk_job_id, chunk_payload = mock_store_payload.call_args.args
    assert chunk_job_id == 999
    assert chunk_payload["diff"] == "123456"
    assert chunk_payload["resolved_user"] == "TargetUser"
    assert chunk_payload["resolved_timestamp"] == "2026-03-25T03:30:00Z"
    assert chunk_payload["contribs_query"]["list"] == "usercontribs"
    assert chunk_payload["source_job_id"] == 1


def test_cancel_job_returns_401_when_not_authenticated(client):
    resp = client.delete("/api/v1/rollback/jobs/1")
    assert resp.status_code == 401


def test_cancel_job_returns_404_when_not_found(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = None
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.delete("/api/v1/rollback/jobs/999")
    assert resp.status_code == 404


def test_cancel_job_returns_403_when_owned_by_different_user(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "bob", "queued")
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.delete("/api/v1/rollback/jobs/1")
    assert resp.status_code == 403


def test_cancel_job_marks_job_and_items_canceled(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "alice", "queued")
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.delete("/api/v1/rollback/jobs/1")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "canceled"


def test_cancel_job_allows_status_token_auth(client):
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "statusbot", "queued")
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch.dict(
            "router.os.environ",
            {"STATUS_API_TOKEN": "token123", "STATUS_API_USER": "statusbot"},
            clear=False,
        ),
    ):
        resp = client.delete(
            "/api/v1/rollback/jobs/1", headers={"X-Status-Token": "token123"}
        )
    assert resp.status_code == 200


# ── GET /api/v1/rollback/jobs/<id> ────────────────────────────────────────────


def test_get_job_returns_401_when_not_authenticated(client):
    resp = client.get("/api/v1/rollback/jobs/1")
    assert resp.status_code == 401


def test_get_job_returns_404_when_not_found(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = None
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.get("/api/v1/rollback/jobs/999")
    assert resp.status_code == 404


def test_get_job_returns_403_when_owned_by_different_user(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "bob", "completed", 0, "2024-01-01")
    mock_cursor.fetchall.return_value = []
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=False),
    ):
        resp = client.get("/api/v1/rollback/jobs/1")
    assert resp.status_code == 403


def test_get_job_allows_maintainer_for_other_user(client):
    _set_session(client, "maintainer")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "bob", "completed", 0, "2024-01-01")
    mock_cursor.fetchall.return_value = [
        (10, "File:Test.jpg", "Vandal", None, "completed", None),
    ]
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=True),
    ):
        resp = client.get("/api/v1/rollback/jobs/1")
    assert resp.status_code == 200
    assert resp.get_json()["requested_by"] == "bob"


def test_get_job_log_format_returns_plain_text(client):
    _set_session(client, "maintainer")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "bob", "failed", 0, "2024-01-01")
    mock_cursor.fetchall.return_value = [
        (10, "File:Test.jpg", "Vandal", None, "failed", "Rollback failed"),
    ]
    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=True),
    ):
        resp = client.get("/api/v1/rollback/jobs/1?format=log")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers.get("Content-Type", "")
    body = resp.get_data(as_text=True)
    assert "item_id=10" in body
    assert "status=failed" in body
    assert "Rollback failed" in body


def test_get_job_returns_full_detail_for_owner(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "alice", "completed", 0, "2024-01-01")
    mock_cursor.fetchall.return_value = [
        (10, "File:Test.jpg", "Vandal", None, "completed", None),
    ]
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.get("/api/v1/rollback/jobs/1")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["id"] == 1
    assert data["requested_by"] == "alice"
    assert data["status"] == "completed"
    assert data["total"] == 1
    assert data["completed"] == 1
    assert data["failed"] == 0
    assert data["items"][0]["title"] == "File:Test.jpg"


def test_get_job_exposes_dry_run_flag(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (2, "alice", "queued", 1, "2024-01-01")
    mock_cursor.fetchall.return_value = []
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.get("/api/v1/rollback/jobs/2")
    assert resp.get_json()["dry_run"] is True


# ── GET /api/v1/rollback/jobs ─────────────────────────────────────────────────


def test_list_jobs_returns_401_when_not_authenticated(client):
    resp = client.get("/api/v1/rollback/jobs")
    assert resp.status_code == 401


def test_list_jobs_returns_jobs_for_authenticated_user(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchall.return_value = [
        (1, "alice", "queued", 0, "2024-01-01"),
        (2, "alice", "completed", 1, "2024-01-02"),
    ]
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.get("/api/v1/rollback/jobs")
    assert resp.status_code == 200
    jobs = resp.get_json()["jobs"]
    assert len(jobs) == 2
    assert all(j["requested_by"] == "alice" for j in jobs)


def test_list_jobs_response_shape(client):
    """Each job row must include id, requested_by, status, dry_run, created_at."""
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchall.return_value = [(3, "alice", "running", 0, "2024-06-01")]
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.get("/api/v1/rollback/jobs")
    job = resp.get_json()["jobs"][0]
    assert {"id", "requested_by", "status", "dry_run", "created_at"} <= job.keys()


# ── GET /rollback-queue (UI) ──────────────────────────────────────────────────


def test_rollback_queue_ui_returns_200_for_unauthenticated_user(client):
    resp = client.get("/rollback-queue")
    assert resp.status_code == 200


def test_rollback_queue_ui_contains_web_tool_forms(client):
    resp = client.get("/rollback-queue")
    html = resp.get_data(as_text=True)
    assert "Rollback job queue" in html
    assert "rollback-queue-props" in html


def test_rollback_queue_ui_returns_200_for_authenticated_user(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchall.return_value = []
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.get("/rollback-queue")
    assert resp.status_code == 200


def test_all_jobs_ui_returns_401_when_not_authenticated(client):
    resp = client.get("/rollback-queue/all-jobs")
    assert resp.status_code == 401


def test_all_jobs_ui_returns_403_for_non_maintainer(client):
    _set_session(client, "alice")
    with patch("router.is_maintainer", return_value=False):
        resp = client.get("/rollback-queue/all-jobs")
    assert resp.status_code == 403


def test_all_jobs_ui_returns_200_for_maintainer(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchall.return_value = []
    with (
        patch("router.is_maintainer", return_value=True),
        patch("router.get_conn", return_value=mock_conn),
    ):
        resp = client.get("/rollback-queue/all-jobs")
    assert resp.status_code == 200
    assert "All rollback jobs" in resp.get_data(as_text=True)


# ── GET / ─────────────────────────────────────────────────────────────────────


def test_index_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_login_does_not_500_when_secret_key_missing(client):
    import router

    original = router.app.config.get("SECRET_KEY")
    router.app.config["SECRET_KEY"] = None
    with (
        patch.dict(
            "router.os.environ",
            {
                "SECRET_KEY": "",
                "FALLBACK_SECRET_KEY": "fallback-secret",
                "USER_OAUTH_CONSUMER_KEY": "k",
                "USER_OAUTH_CONSUMER_SECRET": "s",
            },
            clear=False,
        ),
        patch(
            "router.mwoauth.initiate", return_value=("https://example.test", ("a", "b"))
        ),
    ):
        resp = client.get("/login")
    router.app.config["SECRET_KEY"] = original
    assert resp.status_code == 302


def test_login_redirects_to_index_when_consumer_creds_missing(client):
    with patch.dict(
        "router.os.environ",
        {"USER_OAUTH_CONSUMER_KEY": "", "USER_OAUTH_CONSUMER_SECRET": ""},
        clear=False,
    ):
        resp = client.get("/login")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_login_uses_current_site_callback_url_by_default(client):
    with (
        patch.dict(
            "router.os.environ",
            {
                "USER_OAUTH_CALLBACK_URL": "",
                "USER_OAUTH_CONSUMER_KEY": "k",
                "USER_OAUTH_CONSUMER_SECRET": "s",
            },
            clear=False,
        ),
        patch(
            "router.mwoauth.initiate", return_value=("https://example.test", ("a", "b"))
        ) as mock_initiate,
    ):
        resp = client.get("/login")

    assert resp.status_code == 302
    assert (
        mock_initiate.call_args.kwargs["callback"]
        == "https://buckbot.toolforge.org/mas-oauth-callback"
    )


def test_oauth_callback_failure_redirects_index_not_referrer(client):
    with client.session_transaction() as sess:
        sess["request_token"] = {"key": "rk", "secret": "rs"}
        sess["referrer"] = "/rollback-queue"

    with (
        patch.dict(
            "router.os.environ",
            {"USER_OAUTH_CONSUMER_KEY": "k", "USER_OAUTH_CONSUMER_SECRET": "s"},
            clear=False,
        ),
        patch("router.mwoauth.complete", side_effect=RuntimeError("bad oauth")),
    ):
        resp = client.get("/oauth-callback")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_oauth_callback_alias_routes_exist(client):
    resp1 = client.get("/oauth-callback")
    resp2 = client.get("/mwoauth-callback")
    resp3 = client.get("/buckbot-oauth-callback")
    assert resp1.status_code == 302
    assert resp2.status_code == 302
    assert resp3.status_code == 302


# ── GET /logout ────────────────────────────────────────────────────────────────


def test_logout_clears_session_and_redirects(client):
    _set_session(client, "alice")
    resp = client.get("/logout")
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get("username") is None


# ── GET /goto ────────────────────────────────────────────���────────────────────


def test_goto_redirects_unauthenticated_user_to_login(client):
    resp = client.get("/goto?tab=rollback-queue")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_goto_rollback_queue_tab_redirects_to_rollback_queue(client):
    _set_session(client, "alice")
    resp = client.get("/goto?tab=rollback-queue")
    assert resp.status_code == 302
    assert "/rollback-queue" in resp.headers["Location"]


def test_goto_all_jobs_tab_redirects_for_maintainer(client):
    _set_session(client, "alice")
    with patch("router.is_maintainer", return_value=True):
        resp = client.get("/goto?tab=rollback-all-jobs")
    assert resp.status_code == 302
    assert "/rollback-queue/all-jobs" in resp.headers["Location"]


def test_goto_all_jobs_tab_returns_403_for_non_maintainer(client):
    _set_session(client, "alice")
    with patch("router.is_maintainer", return_value=False):
        resp = client.get("/goto?tab=rollback-all-jobs")
    assert resp.status_code == 403


def test_goto_from_diff_tab_redirects_for_maintainer(client):
    _set_session(client, "alice")
    with patch("router.is_maintainer", return_value=True):
        resp = client.get("/goto?tab=rollback-from-diff")
    assert resp.status_code == 302
    assert "/rollback-from-diff" in resp.headers["Location"]


def test_goto_from_diff_tab_returns_403_for_non_maintainer(client):
    _set_session(client, "alice")
    with patch("router.is_maintainer", return_value=False):
        resp = client.get("/goto?tab=rollback-from-diff")
    assert resp.status_code == 403


def test_goto_runtime_config_tab_redirects_for_bot_admin(client):
    _set_session(client, "chuckbot")
    with patch("router.is_bot_admin", return_value=True):
        resp = client.get("/goto?tab=rollback-config")
    assert resp.status_code == 302
    assert "/rollback-config" in resp.headers["Location"]


def test_goto_runtime_config_tab_returns_403_for_non_bot_admin(client):
    _set_session(client, "alice")
    with patch("router.is_bot_admin", return_value=False):
        resp = client.get("/goto?tab=rollback-config")
    assert resp.status_code == 403


# ── EXTRA_AUTHORIZED_USERS ────────────────────────────────────────────────────


def test_is_authorized_returns_true_for_extra_authorized_user():
    """A user listed in EXTRA_AUTHORIZED_USERS is authorized."""
    import router

    with patch.object(router, "EXTRA_AUTHORIZED_USERS", {"testuser"}):
        with patch("router.is_maintainer", return_value=False):
            assert router.is_authorized("TestUser") is True


def test_is_authorized_extra_authorized_user_is_case_insensitive():
    """EXTRA_AUTHORIZED_USERS matching is case-insensitive."""
    import router

    with patch.object(router, "EXTRA_AUTHORIZED_USERS", {"testuser"}):
        with patch("router.is_maintainer", return_value=False):
            assert router.is_authorized("TESTUSER") is True
            assert router.is_authorized("testuser") is True
            assert router.is_authorized("TestUser") is True


def test_is_authorized_returns_false_for_unknown_user():
    """A user not in any authorized list or group is denied."""
    import router

    with patch.object(router, "EXTRA_AUTHORIZED_USERS", set()):
        with patch("router.is_maintainer", return_value=False):
            with patch("router.get_user_groups", return_value=[]):
                assert router.is_authorized("nobody") is False


def test_extra_authorized_user_is_not_granted_maintainer_status():
    """EXTRA_AUTHORIZED_USERS grants authorization only, not maintainer rights."""
    import router
    from app import is_maintainer

    with patch.object(router, "EXTRA_AUTHORIZED_USERS", {"testuser"}):
        # The user is authorized …
        with patch("router.is_maintainer", return_value=False):
            assert router.is_authorized("testuser") is True
        # … but is_maintainer is not affected by EXTRA_AUTHORIZED_USERS.
        assert is_maintainer("testuser") is False


# ── _user_permissions ─────────────────────────────────────────────────────────


def test_user_permissions_base_perms_for_regular_user():
    """Authenticated non-maintainer users get the standard base permission set."""
    import router

    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_READ_ONLY", set()),
    ):
        perms = router._user_permissions("alice")

    assert perms == frozenset({"read_own", "write", "cancel_own", "retry_own"})


def test_user_permissions_empty_username_returns_empty():
    """An empty username yields an empty permission set."""
    import router

    assert router._user_permissions("") == frozenset()


def test_user_permissions_read_only_user_gets_only_read_own():
    """Users in USERS_READ_ONLY can only view their own jobs."""
    import router

    with patch.object(router, "USERS_READ_ONLY", {"readonly"}):
        perms = router._user_permissions("readonly")

    assert perms == frozenset({"read_own"})
    assert "write" not in perms
    assert "cancel_own" not in perms
    assert "retry_own" not in perms


def test_user_permissions_read_only_matching_is_case_insensitive():
    """USERS_READ_ONLY matching is case-insensitive."""
    import router

    with patch.object(router, "USERS_READ_ONLY", {"readonly"}):
        assert "write" not in router._user_permissions("READONLY")
        assert "write" not in router._user_permissions("ReadOnly")
        assert "write" not in router._user_permissions("readonly")


def test_user_permissions_maintainer_gets_all_permissions():
    """Maintainers receive every available non-bot-admin permission, including cancel_admin_jobs."""
    import router

    with (
        patch("router.is_maintainer", return_value=True),
        patch("router.is_bot_admin", return_value=False),
    ):
        perms = router._user_permissions("maintainer")

    for perm in (
        "read_own",
        "write",
        "cancel_own",
        "retry_own",
        "read_all",
        "from_diff",
        "batch",
        "cancel_any",
        "retry_any",
        "cancel_admin_jobs",
    ):
        assert perm in perms, f"Expected '{perm}' in maintainer permissions"

    assert "cancel_maintainer_jobs" not in perms


def test_user_permissions_granted_from_diff():
    """USERS_GRANTED_FROM_DIFF gives the from_diff permission without full maintainer rights."""
    import router

    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_FROM_DIFF", {"alice"}),
    ):
        perms = router._user_permissions("alice")

    assert "from_diff" in perms
    assert "read_all" not in perms
    assert "batch" not in perms


def test_user_permissions_granted_view_all():
    """USERS_GRANTED_VIEW_ALL gives the read_all permission."""
    import router

    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_VIEW_ALL", {"alice"}),
    ):
        perms = router._user_permissions("alice")

    assert "read_all" in perms
    assert "from_diff" not in perms


def test_user_permissions_granted_cancel_any():
    """USERS_GRANTED_CANCEL_ANY gives the cancel_any permission."""
    import router

    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_CANCEL_ANY", {"alice"}),
    ):
        perms = router._user_permissions("alice")

    assert "cancel_any" in perms
    assert "retry_any" not in perms


def test_user_permissions_granted_retry_any():
    """USERS_GRANTED_RETRY_ANY gives the retry_any permission."""
    import router

    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_RETRY_ANY", {"alice"}),
    ):
        perms = router._user_permissions("alice")

    assert "retry_any" in perms
    assert "cancel_any" not in perms


def test_user_permissions_multiple_grants_accumulate():
    """Multiple per-user grants are all reflected in the returned permission set."""
    import router

    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_FROM_DIFF", {"alice"}),
        patch.object(router, "USERS_GRANTED_VIEW_ALL", {"alice"}),
        patch.object(router, "USERS_GRANTED_BATCH", {"alice"}),
    ):
        perms = router._user_permissions("alice")

    assert "from_diff" in perms
    assert "read_all" in perms
    assert "batch" in perms
    assert "cancel_any" not in perms
    assert "retry_any" not in perms


# ── _check_rate_limit ─────────────────────────────────────────────────────────


def test_check_rate_limit_disabled_when_zero():
    """Rate limiting is off by default (RATE_LIMIT_JOBS_PER_HOUR=0)."""
    import router

    with patch.object(router, "RATE_LIMIT_JOBS_PER_HOUR", 0):
        assert router._check_rate_limit("alice") is True


def test_check_rate_limit_allows_when_within_limit():
    """A user whose counter is below the limit is not blocked."""
    import router

    mock_r = MagicMock()
    mock_r.incr.return_value = 3

    with (
        patch.object(router, "RATE_LIMIT_JOBS_PER_HOUR", 10),
        patch.object(router, "r", mock_r),
    ):
        assert router._check_rate_limit("alice") is True


def test_check_rate_limit_blocks_when_exceeded():
    """A user whose counter has exceeded the limit is blocked."""
    import router

    mock_r = MagicMock()
    mock_r.incr.return_value = 11

    with (
        patch.object(router, "RATE_LIMIT_JOBS_PER_HOUR", 10),
        patch.object(router, "r", mock_r),
    ):
        assert router._check_rate_limit("alice") is False


def test_check_rate_limit_allows_at_exact_limit():
    """A counter exactly equal to the limit is still allowed."""
    import router

    mock_r = MagicMock()
    mock_r.incr.return_value = 10

    with (
        patch.object(router, "RATE_LIMIT_JOBS_PER_HOUR", 10),
        patch.object(router, "r", mock_r),
    ):
        assert router._check_rate_limit("alice") is True


def test_check_rate_limit_sets_expiry_on_new_bucket():
    """The first increment in a bucket sets a 2-hour TTL for auto-cleanup."""
    import router

    mock_r = MagicMock()
    mock_r.incr.return_value = 1

    with (
        patch.object(router, "RATE_LIMIT_JOBS_PER_HOUR", 5),
        patch.object(router, "r", mock_r),
    ):
        router._check_rate_limit("alice")

    mock_r.expire.assert_called_once()
    assert mock_r.expire.call_args.args[1] == 7200


def test_check_rate_limit_does_not_set_expiry_on_subsequent_increments():
    """Subsequent increments in the same bucket do not reset the TTL."""
    import router

    mock_r = MagicMock()
    mock_r.incr.return_value = 4

    with (
        patch.object(router, "RATE_LIMIT_JOBS_PER_HOUR", 5),
        patch.object(router, "r", mock_r),
    ):
        router._check_rate_limit("alice")

    mock_r.expire.assert_not_called()


def test_check_rate_limit_fails_open_on_redis_error():
    """A Redis failure does not block job submission (fail-open)."""
    import router

    mock_r = MagicMock()
    mock_r.incr.side_effect = Exception("Redis unavailable")

    with (
        patch.object(router, "RATE_LIMIT_JOBS_PER_HOUR", 10),
        patch.object(router, "r", mock_r),
    ):
        assert router._check_rate_limit("alice") is True


# ── write permission & rate-limiting on POST /api/v1/rollback/jobs ────────────


def test_create_job_returns_403_for_read_only_user(client):
    """A user in USERS_READ_ONLY cannot submit new rollback jobs."""
    import router

    _set_session(client, "viewer")
    with patch.object(router, "USERS_READ_ONLY", {"viewer"}):
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": "viewer",
                "items": [{"title": "File:T.jpg", "user": "V"}],
            },
        )
    assert resp.status_code == 403
    assert "write" in resp.get_json().get("detail", "").lower()


def test_create_job_returns_429_when_rate_limited(client):
    """A user who has exceeded the rate limit receives a 429 response."""
    _set_session(client, "alice")
    with (
        patch("router.is_maintainer", return_value=False),
        patch("router._check_rate_limit", return_value=False),
    ):
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": "alice",
                "items": [{"title": "File:T.jpg", "user": "V"}],
            },
        )
    assert resp.status_code == 429
    assert "rate limit" in resp.get_json().get("detail", "").lower()


def test_create_job_succeeds_when_rate_limit_disabled(client):
    """With rate limiting off the route behaves as before."""
    import router

    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.lastrowid = 42

    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "RATE_LIMIT_JOBS_PER_HOUR", 0),
        patch("router.get_conn", return_value=mock_conn),
        patch("router.process_rollback_job") as mock_task,
    ):
        mock_task.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={
                "requested_by": "alice",
                "items": [{"title": "File:T.jpg", "user": "V"}],
            },
        )
    assert resp.status_code == 200


# ── cancel_any permission on DELETE /api/v1/rollback/jobs/<id> ───────────────


def test_cancel_job_allowed_for_cancel_any_user_on_others_job(client):
    """A user with cancel_any permission can cancel another user's job."""
    import router

    _set_session(client, "admin")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "bob", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_CANCEL_ANY", {"admin"}),
    ):
        resp = client.delete("/api/v1/rollback/jobs/1")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "canceled"


def test_cancel_job_still_forbidden_without_cancel_any(client):
    """A non-privileged user cannot cancel someone else's job."""
    import router

    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "bob", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_CANCEL_ANY", set()),
    ):
        resp = client.delete("/api/v1/rollback/jobs/1")

    assert resp.status_code == 403


# ── retry_any permission on POST /api/v1/rollback/jobs/<id>/retry ─────────────


def test_retry_job_allowed_for_retry_any_user_on_others_job(client):
    """A user with retry_any permission can retry another user's job."""
    import router

    _set_session(client, "admin")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.side_effect = [("bob",), (1,)]

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_RETRY_ANY", {"admin"}),
        patch("router.process_rollback_job") as mock_task,
    ):
        mock_task.delay = MagicMock()
        resp = client.post("/api/v1/rollback/jobs/1/retry")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "queued"


def test_retry_job_still_forbidden_without_retry_any(client):
    """A non-privileged user cannot retry someone else's job."""
    import router

    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = ("bob",)

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_RETRY_ANY", set()),
    ):
        resp = client.post("/api/v1/rollback/jobs/1/retry")

    assert resp.status_code == 403


# ── read_all permission on GET /api/v1/rollback/jobs/<id> ─────────────────────


def test_get_job_allowed_for_view_all_user_on_others_job(client):
    """A user with read_all permission can view another user's job."""
    import router

    _set_session(client, "watcher")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "bob", "completed", 0, "2024-01-01")
    mock_cursor.fetchall.return_value = []

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_VIEW_ALL", {"watcher"}),
    ):
        resp = client.get("/api/v1/rollback/jobs/1")

    assert resp.status_code == 200
    assert resp.get_json()["requested_by"] == "bob"


def test_get_job_still_forbidden_without_read_all(client):
    """A user without read_all cannot view another user's job."""
    import router

    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "bob", "completed", 0, "2024-01-01")
    mock_cursor.fetchall.return_value = []

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_VIEW_ALL", set()),
    ):
        resp = client.get("/api/v1/rollback/jobs/1")

    assert resp.status_code == 403


# ── from_diff interface grant ─────────────────────────────────────────────────


def test_from_diff_api_allowed_for_granted_user(client):
    """A non-maintainer in USERS_GRANTED_FROM_DIFF can use the from-diff API."""
    import router

    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.lastrowid = 11

    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_FROM_DIFF", {"alice"}),
        patch("router.get_conn", return_value=mock_conn),
        patch("router.resolve_diff_rollback_job") as mock_resolve,
    ):
        mock_resolve.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/from-diff",
            json={"diff": 999, "limit": 5},
        )

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "resolving"


def test_from_diff_api_still_denied_without_grant(client):
    """A non-maintainer user without USERS_GRANTED_FROM_DIFF cannot use the from-diff API."""
    import router

    _set_session(client, "alice")
    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_FROM_DIFF", set()),
    ):
        resp = client.post(
            "/api/v1/rollback/from-diff",
            json={"diff": 999},
        )

    assert resp.status_code == 403


def test_all_jobs_ui_allowed_for_view_all_granted_user(client):
    """A non-maintainer in USERS_GRANTED_VIEW_ALL can access the all-jobs page."""
    import router

    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchall.return_value = []

    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_VIEW_ALL", {"alice"}),
        patch("router.get_conn", return_value=mock_conn),
    ):
        resp = client.get("/rollback-queue/all-jobs")

    assert resp.status_code == 200


def test_goto_from_diff_tab_allowed_for_granted_user(client):
    """A non-maintainer user with from_diff grant is redirected correctly by /goto."""
    import router

    _set_session(client, "alice")
    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_GRANTED_FROM_DIFF", {"alice"}),
    ):
        resp = client.get("/goto?tab=rollback-from-diff")

    assert resp.status_code == 302
    assert "/rollback-from-diff" in resp.headers["Location"]


# ── is_bot_admin ──────────────────────────────────────────────────────────────


def test_is_bot_admin_returns_true_for_bot_admin_account():
    """A username listed in BOT_ADMIN_ACCOUNTS is a bot admin."""
    import router

    with patch.object(router, "BOT_ADMIN_ACCOUNTS", {"chuckbot"}):
        assert router.is_bot_admin("chuckbot") is True
        assert router.is_bot_admin("ChuckBot") is True   # case-insensitive


def test_is_bot_admin_returns_false_for_regular_user():
    """A username not in BOT_ADMIN_ACCOUNTS is not a bot admin."""
    import router

    with patch.object(router, "BOT_ADMIN_ACCOUNTS", {"chuckbot"}):
        assert router.is_bot_admin("alice") is False


def test_is_bot_admin_returns_false_for_empty_username():
    """An empty username is never a bot admin."""
    import router

    assert router.is_bot_admin("") is False


# ── _user_permissions – cancel tier permissions ───────────────────────────────


def test_user_permissions_bot_admin_gets_cancel_maintainer_jobs():
    """Bot admins (chuckbot) receive cancel_maintainer_jobs on top of all maintainer perms."""
    import router

    with (
        patch("router.is_maintainer", return_value=True),
        patch("router.is_bot_admin", return_value=True),
    ):
        perms = router._user_permissions("chuckbot")

    assert "cancel_maintainer_jobs" in perms
    assert "cancel_admin_jobs" in perms


def test_user_permissions_regular_maintainer_does_not_get_cancel_maintainer_jobs():
    """Non-bot-admin maintainers do not receive cancel_maintainer_jobs."""
    import router

    with (
        patch("router.is_maintainer", return_value=True),
        patch("router.is_bot_admin", return_value=False),
    ):
        perms = router._user_permissions("maintainer")

    assert "cancel_maintainer_jobs" not in perms
    assert "cancel_admin_jobs" in perms


def test_user_permissions_admin_sysop_does_not_get_cancel_admin_jobs():
    """A sysop who is not a maintainer does NOT receive cancel_admin_jobs."""
    import router

    with (
        patch("router.is_maintainer", return_value=False),
        patch.object(router, "USERS_READ_ONLY", set()),
    ):
        perms = router._user_permissions("sysop_alice")

    assert "cancel_admin_jobs" not in perms
    assert "cancel_maintainer_jobs" not in perms


# ── cancel_rollback_job – three-tier ownership (chuckbot > maintainer > admin > regular) ───


def test_cancel_job_returns_403_when_owner_is_maintainer_and_actor_has_only_cancel_any(client):
    """An env-granted cancel_any user cannot cancel a maintainer's job."""
    import router

    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "maintaineruser", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", side_effect=lambda u: u == "maintaineruser"),
        patch("router.is_admin_user", return_value=False),
        patch.object(router, "USERS_GRANTED_CANCEL_ANY", {"alice"}),
    ):
        resp = client.delete("/api/v1/rollback/jobs/1")

    assert resp.status_code == 403
    assert "maintainer" in resp.get_json().get("detail", "").lower()


def test_cancel_job_allowed_when_owner_is_regular_maintainer_and_actor_is_also_maintainer(client):
    """A maintainer can cancel another regular maintainer's job."""
    import router

    _set_session(client, "maint_alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "maint_bob", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=True),
        patch("router.is_bot_admin", return_value=False),
        patch("router.is_admin_user", return_value=False),
    ):
        resp = client.delete("/api/v1/rollback/jobs/1")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "canceled"


def test_cancel_job_allowed_when_owner_is_maintainer_and_actor_is_bot_admin(client):
    """A bot admin can cancel a maintainer's job."""
    import router

    _set_session(client, "chuckbot")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "maint_bob", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=True),
        patch("router.is_bot_admin", side_effect=lambda u: u == "chuckbot"),
        patch("router.is_admin_user", return_value=False),
    ):
        resp = client.delete("/api/v1/rollback/jobs/1")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "canceled"


def test_cancel_job_returns_403_when_owner_is_bot_admin_and_actor_is_regular_maintainer(client):
    """A regular maintainer cannot cancel chuckbot's job."""
    import router

    _set_session(client, "maint_alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "chuckbot", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=True),
        patch("router.is_bot_admin", side_effect=lambda u: u == "chuckbot"),
        patch("router.is_admin_user", return_value=False),
    ):
        resp = client.delete("/api/v1/rollback/jobs/1")

    assert resp.status_code == 403
    assert "bot-admin" in resp.get_json().get("detail", "").lower()


def test_cancel_job_allowed_when_owner_is_bot_admin_and_actor_is_also_bot_admin(client):
    """A bot admin can cancel another bot admin's own job."""
    import router

    _set_session(client, "chuckbot2")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "chuckbot", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=True),
        patch("router.is_bot_admin", return_value=True),
        patch("router.is_admin_user", return_value=False),
    ):
        resp = client.delete("/api/v1/rollback/jobs/1")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "canceled"


def test_cancel_job_returns_403_when_owner_is_admin_and_actor_has_only_cancel_any(client):
    """An env-granted cancel_any user cannot cancel a sysop admin's job."""
    import router

    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "sysop_bob", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=False),
        patch("router.is_admin_user", side_effect=lambda u: u == "sysop_bob"),
        patch.object(router, "USERS_GRANTED_CANCEL_ANY", {"alice"}),
    ):
        resp = client.delete("/api/v1/rollback/jobs/1")

    assert resp.status_code == 403
    assert "maintainer" in resp.get_json().get("detail", "").lower()


def test_cancel_job_allowed_when_owner_is_admin_and_actor_is_maintainer(client):
    """A maintainer can cancel a sysop admin's job."""
    import router

    _set_session(client, "maint_alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "sysop_bob", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", side_effect=lambda u: u == "maint_alice"),
        patch("router.is_bot_admin", return_value=False),
        patch("router.is_admin_user", side_effect=lambda u: u == "sysop_bob"),
    ):
        resp = client.delete("/api/v1/rollback/jobs/1")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "canceled"


def test_cancel_job_returns_403_when_regular_user_tries_to_cancel_admin_job(client):
    """A regular (non-maintainer) user cannot cancel an admin's job."""
    import router

    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "sysop_bob", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=False),
    ):
        resp = client.delete("/api/v1/rollback/jobs/1")

    # Fast-path fires before tier check; no elevated cancel perms → 403.
    assert resp.status_code == 403


def test_cancel_job_allowed_for_cancel_any_user_on_regular_users_job(client):
    """An env-granted cancel_any user CAN cancel a regular (non-admin, non-maintainer) user's job."""
    import router

    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "bob", "queued")

    with (
        patch("router.get_conn", return_value=mock_conn),
        patch("router.is_maintainer", return_value=False),
        patch("router.is_admin_user", return_value=False),
        patch.object(router, "USERS_GRANTED_CANCEL_ANY", {"alice"}),
    ):
        resp = client.delete("/api/v1/rollback/jobs/1")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "canceled"


# ── runtime config permissions and API ───────────────────────────────────────


def test_user_permissions_config_view_for_bot_admin_and_config_edit_for_chuckbot_only():
    import router

    defaults = router._runtime_authz_defaults()

    with (
        patch("router._effective_runtime_authz_config", return_value=defaults),
        patch("router.is_maintainer", return_value=True),
        patch("router.is_tester", return_value=False),
        patch("router.is_bot_admin", return_value=True),
        patch.object(router, "_CONFIG_EDIT_PRIMARY_ACCOUNT", "chuckbot"),
    ):
        other_bot_perms = router._user_permissions("otherbot")
        chuckbot_perms = router._user_permissions("chuckbot")

    assert "config_view" in other_bot_perms
    assert "config_edit" not in other_bot_perms
    assert "config_view" in chuckbot_perms
    assert "config_edit" in chuckbot_perms


def test_get_runtime_authz_api_returns_401_when_not_authenticated(client):
    resp = client.get("/api/v1/config/authz")
    assert resp.status_code == 401


def test_get_runtime_authz_api_returns_403_for_non_bot_admin(client):
    _set_session(client, "alice")
    with patch("router.is_bot_admin", return_value=False):
        resp = client.get("/api/v1/config/authz")
    assert resp.status_code == 403


def test_get_runtime_authz_api_returns_config_for_bot_admin(client):
    import router

    _set_session(client, "otherbot")
    with (
        patch("router.is_bot_admin", return_value=True),
        patch.object(router, "_CONFIG_EDIT_PRIMARY_ACCOUNT", "chuckbot"),
        patch("router.get_runtime_config", return_value={}),
    ):
        resp = client.get("/api/v1/config/authz")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["can_edit"] is False
    assert "config" in data
    assert "RATE_LIMIT_JOBS_PER_HOUR" in data["config"]
    assert "USERS_GRANTED_FROM_DIFF" in data["config"]


def test_update_runtime_authz_api_returns_403_for_non_chuckbot_bot_admin(client):
    _set_session(client, "otherbot")
    with (
        patch("router.is_bot_admin", return_value=True),
        patch("router.get_runtime_config", return_value={}),
    ):
        resp = client.put(
            "/api/v1/config/authz",
            json={"config": {"RATE_LIMIT_JOBS_PER_HOUR": 20}},
        )

    assert resp.status_code == 403


def test_update_runtime_authz_api_rejects_unknown_key(client):
    _set_session(client, "chuckbot")
    with patch("router.is_bot_admin", return_value=True):
        resp = client.put(
            "/api/v1/config/authz",
            json={"config": {"NOT_A_REAL_KEY": "x"}},
        )

    assert resp.status_code == 400
    assert "Unknown config key" in resp.get_json().get("detail", "")


def test_update_runtime_authz_api_persists_for_chuckbot(client):
    import router

    _set_session(client, "chuckbot")
    default_cfg = router._runtime_authz_defaults()

    with (
        patch("router.is_bot_admin", return_value=True),
        patch("router._persist_runtime_authz_updates") as mock_persist,
        patch("router._effective_runtime_authz_config", return_value=default_cfg),
    ):
        resp = client.put(
            "/api/v1/config/authz",
            json={
                "config": {
                    "EXTRA_AUTHORIZED_USERS": ["TestBot", "AnotherBot"],
                    "RATE_LIMIT_JOBS_PER_HOUR": 42,
                }
            },
        )

    assert resp.status_code == 200
    mock_persist.assert_called_once()
    persisted_updates = mock_persist.call_args.args[0]
    assert persisted_updates["EXTRA_AUTHORIZED_USERS"] == ["anotherbot", "testbot"]
    assert persisted_updates["RATE_LIMIT_JOBS_PER_HOUR"] == 42
