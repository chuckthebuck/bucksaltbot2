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
    resp = client.post("/api/v1/rollback/jobs", json={"requested_by": "user", "items": []})
    assert resp.status_code == 401


def test_create_job_returns_403_when_requester_mismatches_session(client):
    _set_session(client, "alice")
    mock_conn, _ = _make_mock_conn()
    with patch("router.get_conn", return_value=mock_conn), \
         patch("router.process_rollback_job") as mock_task:
        mock_task.delay = MagicMock()
        resp = client.post(
            "/api/v1/rollback/jobs",
            json={"requested_by": "bob", "items": [{"title": "File:T.jpg", "user": "V"}]},
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
    with patch("router.get_conn", return_value=mock_conn), \
         patch("router.process_rollback_job") as mock_task:
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
    with patch("router.get_conn", return_value=mock_conn), \
         patch("router.process_rollback_job") as mock_task:
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
    with patch("router.get_conn", return_value=mock_conn), \
         patch("router.process_rollback_job") as mock_task:
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
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.get("/api/v1/rollback/jobs/1")
    assert resp.status_code == 403


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

def test_rollback_queue_ui_redirects_unauthenticated_user(client):
    resp = client.get("/rollback-queue")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_rollback_queue_ui_returns_200_for_authenticated_user(client):
    _set_session(client, "alice")
    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchall.return_value = []
    with patch("router.get_conn", return_value=mock_conn):
        resp = client.get("/rollback-queue")
    assert resp.status_code == 200


# ── GET / ─────────────────────────────────────────────────────────────────────

def test_index_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


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
