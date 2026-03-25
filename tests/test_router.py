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
