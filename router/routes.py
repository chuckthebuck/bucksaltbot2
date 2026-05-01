"""Flask route handlers and route helper functions."""

import os
import sys as _sys
import secrets
import time

import mwoauth
import mwoauth.flask
import logging

from flask import (
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from app import BOT_ADMIN_ACCOUNTS, flask_app as app  # noqa: F401
from redis_state import get_progress, r


from router.authz import (  # noqa: F401
    _RUNTIME_AUTHZ_ALLOWED_KEYS,
    _USER_SET_CONFIG_KEYS,
    _JSON_CONFIG_KEYS,
    BOT_ADMIN_ACCOUNTS as _BOT_ADMIN_ACCOUNTS,
    _AUTO_GRANT_ROLE_KEYS,
    _USER_GRANT_GROUPS,
    _USER_GRANT_RIGHTS,
    _USER_IMPLICIT_FLAGS,
    _normalize_username,
    _normalize_user_grants_map_input,
    _normalize_auto_grants_map_input,
)
from router.diff_state import _diff_error_key, _maybe_mark_stale_resolving_job_failed

from router.jobs import (
    _REQUEST_TYPE_QUEUE,
    _REQUEST_TYPE_BATCH,
    _REQUEST_TYPE_DIFF,
    _REQUEST_STATUS_PENDING_APPROVAL,
    _APPROVAL_REQUIRED_ADMIN,
    _APPROVAL_REQUIRED_MAINTAINER,
    _ENDPOINT_BATCH,
    _ENDPOINT_FROM_DIFF,
    _ENDPOINT_FROM_ACCOUNT,
    _ALLOWED_DIFF_REQUEST_ENDPOINTS,
    _ALLOWED_REQUEST_TYPES,
)
from router import permissions as _perm  # noqa: F401
from router.permissions import (
    is_authorized,
    _can_view_runtime_config,
    _can_edit_runtime_config,
    _can_manage_user_grants,
)
from router.diff_state import _ACCOUNT_ROLLBACK_MAX_LIMIT, _ROLLBACKABLE_WINDOW_LIMIT
from router.module_registry import (
    get_module_definition,
    list_module_definitions,
    set_module_enabled,
    upsert_module_access,
    user_has_module_access,
    install_remote_module,
)
from router.framework_config import (
    DOCS_URL,
    MWOAUTH_BASE_URL,
    MWOAUTH_INDEX_URL,
    UNAUTHORIZED_MESSAGE,
    WORKER_HEARTBEAT_KEY,
    oauth_callback_url,
)


def _r():
    """Return the router package module (supports test-side patching via router.X)."""
    return _sys.modules.get("router")


def is_maintainer(u):
    _router = _r()
    return _router.is_maintainer(u) if _router else False


def is_bot_admin(u):
    _router = _r()
    return _router.is_bot_admin(u) if _router else False


def is_admin_user(u):
    _router = _r()
    return _router.is_admin_user(u) if _router else False


def get_conn():
    return _r().get_conn()


class _LazyTask:
    def __init__(self, name):
        self._name = name

    def delay(self, *a, **kw):
        return getattr(_r(), self._name).delay(*a, **kw)


process_rollback_job = _LazyTask("process_rollback_job")
resolve_diff_rollback_job = _LazyTask("resolve_diff_rollback_job")


def _load_diff_payload(*a, **kw):
    return _r()._load_diff_payload(*a, **kw)


def _store_diff_payload(*a, **kw):
    return _r()._store_diff_payload(*a, **kw)


def _update_diff_payload(*a, **kw):
    return _r()._update_diff_payload(*a, **kw)


def _set_diff_error(*a, **kw):
    return _r()._set_diff_error(*a, **kw)


def _append_mw_debug(*a, **kw):  # noqa: F811
    return _r()._append_mw_debug(*a, **kw)


class _LazyStatusUpdater:
    def __getattr__(self, name):
        return getattr(_r().status_updater, name)


status_updater = _LazyStatusUpdater()


def _extract_oldid(*a, **kw):
    return _r()._extract_oldid(*a, **kw)


def _normalize_target_user_input(*a, **kw):
    return _r()._normalize_target_user_input(*a, **kw)


def _utc_now_iso(*a, **kw):
    return _r()._utc_now_iso(*a, **kw)


def fetch_diff_author_and_timestamp(*a, **kw):
    return _r().fetch_diff_author_and_timestamp(*a, **kw)


def fetch_rollbackable_window_end_timestamp(*a, **kw):
    return _r().fetch_rollbackable_window_end_timestamp(*a, **kw)


def fetch_recent_rollbackable_contribs(*a, **kw):
    return _r().fetch_recent_rollbackable_contribs(*a, **kw)


def iter_contribs_after_timestamp(*a, **kw):
    return _r().iter_contribs_after_timestamp(*a, **kw)


def create_rollback_jobs_from_diff(*a, **kw):
    return _r().create_rollback_jobs_from_diff(*a, **kw)


def resolve_diff_rollback_job_impl(*a, **kw):
    return _r().resolve_diff_rollback_job_impl(*a, **kw)


def _user_permissions(*a, **kw):
    return _r()._user_permissions(*a, **kw)


def _check_rate_limit(*a, **kw):
    return _r()._check_rate_limit(*a, **kw)


def _effective_runtime_authz_config(*a, **kw):
    return _r()._effective_runtime_authz_config(*a, **kw)


def _serialize_runtime_authz_config(*a, **kw):
    return _r()._serialize_runtime_authz_config(*a, **kw)


def _normalize_runtime_authz_updates(*a, **kw):
    return _r()._normalize_runtime_authz_updates(*a, **kw)


def _persist_runtime_authz_updates(*a, **kw):
    return _r()._persist_runtime_authz_updates(*a, **kw)


def _get_user_grants_payload(*a, **kw):
    return _r()._get_user_grants_payload(*a, **kw)


def get_user_groups(*a, **kw):
    return _r().get_user_groups(*a, **kw)


def is_tester(*a, **kw):
    return _r().is_tester(*a, **kw)


def MAX_JOB_ITEMS():
    return _r().MAX_JOB_ITEMS


@app.context_processor
def inject_nav_capabilities():
    """Expose template flags so nav tabs only render when actionable."""
    username = session.get("username")
    if not username:
        return {
            "nav_can_write": False,
            "nav_can_all_jobs": False,
            "nav_is_admin": False,
        }

    perms = _user_permissions(username)
    is_admin = bool(session.get("is_admin") or is_admin_user(username))

    return {
        "nav_can_write": bool("write" in perms),
        "nav_can_all_jobs": bool("read_all" in perms or is_admin),
        "nav_is_admin": is_admin,
    }


def _ensure_secret_key():
    configured = app.config.get("SECRET_KEY") or os.environ.get("SECRET_KEY")
    if not configured:
        configured = os.environ.get(
            "FALLBACK_SECRET_KEY",
            "dev-insecure-secret-change-me",
        )

    app.config["SECRET_KEY"] = configured
    return configured


_ensure_secret_key()


def _user_consumer_token():
    key = os.environ.get("USER_OAUTH_CONSUMER_KEY")
    secret = os.environ.get("USER_OAUTH_CONSUMER_SECRET")

    if not key or not secret:
        return None

    return mwoauth.ConsumerToken(key, secret)


def _serialize_request_token(request_token):
    if isinstance(request_token, dict):
        return request_token

    token_fields = getattr(request_token, "_fields", None)

    if token_fields:
        return dict(zip(token_fields, request_token))

    if isinstance(request_token, (tuple, list)) and len(request_token) == 2:
        return {
            "key": request_token[0],
            "secret": request_token[1],
        }

    raise ValueError("Unsupported request token format")


def _deserialize_request_token(payload):
    if not isinstance(payload, dict):
        raise ValueError("request_token payload must be a dict")

    try:
        return mwoauth.RequestToken(**payload)
    except TypeError:
        key = payload.get("key")
        secret = payload.get("secret")

        if key and secret:
            return mwoauth.RequestToken(key, secret)

        raise


def _oauth_callback_url():
    return oauth_callback_url()


def _rollback_api_actor():
    username = session.get("username")

    if username:
        return username

    status_token = request.headers.get("X-Status-Token")
    expected_token = os.environ.get("STATUS_API_TOKEN")

    if (
        status_token
        and expected_token
        and secrets.compare_digest(status_token, expected_token)
    ):
        return os.environ.get("STATUS_API_USER", "status-site")

    return None


def _parse_bool(value, default=False):
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in {"1", "true", "yes", "on"}:
            return True

        if normalized in {"0", "false", "no", "off", ""}:
            return False

    return default


def _normalize_request_type(raw_value) -> str:
    value = str(raw_value or "").strip().lower()
    if value in _ALLOWED_REQUEST_TYPES:
        return value
    return _REQUEST_TYPE_QUEUE


def _normalize_request_endpoint(raw_value) -> str | None:
    value = str(raw_value or "").strip().lower().replace("-", "_")
    return value or None


def _approval_requirement_for_request(
    request_type: str, requested_endpoint: str | None
) -> str | None:
    if request_type == _REQUEST_TYPE_BATCH or requested_endpoint == _ENDPOINT_BATCH:
        return _APPROVAL_REQUIRED_ADMIN
    if request_type == _REQUEST_TYPE_DIFF:
        return _APPROVAL_REQUIRED_MAINTAINER
    return None


def _can_actor_approve_impl(actor: str, required_level: str | None) -> bool:
    if not actor or not required_level:
        return False

    if "approve_jobs" in _user_permissions(actor):
        return True

    if required_level == _APPROVAL_REQUIRED_MAINTAINER:
        return is_maintainer(actor)

    if required_level == _APPROVAL_REQUIRED_ADMIN:
        return is_maintainer(actor) or is_admin_user(actor)

    return False


def _can_actor_approve(actor: str, required_level: str | None) -> bool:
    """Entry point for route handlers; allows patching at ``router._can_actor_approve``."""
    _router = _r()
    fn = getattr(_router, "_can_actor_approve", None) if _router else None
    if fn is not None and fn is not _can_actor_approve:
        return fn(actor, required_level)
    return _can_actor_approve_impl(actor, required_level)


def _can_review_requests_impl(username: str) -> bool:
    if not username:
        return False
    return is_maintainer(username) or is_admin_user(username)


def _can_review_requests(username: str) -> bool:
    """Entry point for route handlers; allows patching at ``router._can_review_requests``."""
    _router = _r()
    fn = getattr(_router, "_can_review_requests", None) if _router else None
    if fn is not None and fn is not _can_review_requests:
        return fn(username)
    return _can_review_requests_impl(username)


def _can_run_live_impl(
    actor: str, requested_by: str, approval_required: str | None
) -> bool:
    """Return whether *actor* may re-run a completed dry-run job live."""
    if not actor:
        return False

    if actor == requested_by:
        return True

    if _can_actor_approve(actor, approval_required):
        return True

    return "retry_any" in _user_permissions(actor)


def _can_run_live(actor: str, requested_by: str, approval_required: str | None) -> bool:
    """Entry point for route handlers; allows patching at ``router._can_run_live``."""
    _router = _r()
    fn = getattr(_router, "_can_run_live", None) if _router else None
    if fn is not None and fn is not _can_run_live:
        return fn(actor, requested_by, approval_required)
    return _can_run_live_impl(actor, requested_by, approval_required)


def _should_autoapprove_request(actor: str, required_level: str | None) -> bool:
    """Return True when test-mode requests should skip manual approval.

    This is intentionally restricted to test runs with an explicit opt-in env var
    to avoid changing production approval workflows.
    """
    if not actor or not required_level:
        return False

    if not app.config.get("TESTING"):
        return False

    if not _parse_bool(
        os.environ.get("LIVE_TEST_AUTO_APPROVE_REQUESTS"), default=False
    ):
        return False

    if "autoapprove_jobs" not in _user_permissions(actor):
        return False

    return _can_actor_approve(actor, required_level)


def _pending_batch_request_job_ids(
    cursor, batch_id: int, request_type: str
) -> list[int]:
    cursor.execute(
        """
        SELECT id
        FROM rollback_jobs
        WHERE batch_id=%s AND request_type=%s AND status=%s
        ORDER BY id ASC
        """,
        (batch_id, request_type, _REQUEST_STATUS_PENDING_APPROVAL),
    )
    return [int(row[0]) for row in cursor.fetchall()]


def _request_payload_has_diff_anchor(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False

    for key in ("diff", "oldid", "resolved_timestamp"):
        if payload.get(key) not in (None, ""):
            return True

    return False


def _compute_diff_request_preview(
    job_id: int,
    payload: dict,
    endpoint: str,
    full_from_diff: bool = True,
) -> dict:
    """Compute and cache preview edits for a diff-style request endpoint."""
    if endpoint not in _ALLOWED_DIFF_REQUEST_ENDPOINTS:
        raise ValueError("Unsupported endpoint for diff request preview")

    preview_by_endpoint = payload.get("preview_by_endpoint")
    if not isinstance(preview_by_endpoint, dict):
        preview_by_endpoint = {}

    cache_key = f"{endpoint}:{'full' if (endpoint == _ENDPOINT_FROM_DIFF and full_from_diff) else 'limited'}"
    cached = preview_by_endpoint.get(cache_key)
    if isinstance(cached, dict) and isinstance(cached.get("items"), list):
        return cached

    limit_raw = payload.get("limit")
    limit = None
    if limit_raw not in (None, ""):
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ValueError("limit must be an integer")
        if limit <= 0:
            raise ValueError("limit must be a positive integer")

    diff = payload.get("diff")
    target_user = _normalize_target_user_input(payload.get("target_user"))
    oldid = payload.get("oldid")
    start_timestamp = payload.get("resolved_timestamp")

    if diff not in (None, ""):
        if oldid in (None, ""):
            oldid = _extract_oldid(diff)
        diff_metadata = fetch_diff_author_and_timestamp(oldid)
        if not target_user:
            target_user = diff_metadata["user"]
        if not start_timestamp:
            start_timestamp = diff_metadata["timestamp"]

    if not target_user:
        raise ValueError("Unable to resolve target user for request preview")

    items: list[dict] = []
    rollbackable_end_timestamp = None

    if endpoint == _ENDPOINT_FROM_ACCOUNT:
        effective_limit = limit or _ACCOUNT_ROLLBACK_MAX_LIMIT
        if effective_limit > _ACCOUNT_ROLLBACK_MAX_LIMIT:
            raise ValueError(f"limit must be <= {_ACCOUNT_ROLLBACK_MAX_LIMIT}")
        items = fetch_recent_rollbackable_contribs(target_user, limit=effective_limit)
    else:
        if not start_timestamp:
            raise ValueError("Diff timestamp is required for from-diff preview")
        rollbackable_end_timestamp = fetch_rollbackable_window_end_timestamp(
            target_user,
            start_timestamp,
            limit=_ROLLBACKABLE_WINDOW_LIMIT,
        )
        items = list(
            iter_contribs_after_timestamp(
                target_user,
                start_timestamp,
                limit=None if full_from_diff else limit,
                end_timestamp=rollbackable_end_timestamp,
                rollbackable_only=True,
            )
        )

    preview_payload = {
        "endpoint": endpoint,
        "oldid": oldid,
        "resolved_user": target_user,
        "resolved_timestamp": start_timestamp,
        "rollbackable_window_end_timestamp": rollbackable_end_timestamp,
        "limit": None
        if (endpoint == _ENDPOINT_FROM_DIFF and full_from_diff)
        else limit,
        "request_limit": limit,
        "full_from_diff": bool(endpoint == _ENDPOINT_FROM_DIFF and full_from_diff),
        "total_items": len(items),
        "items": items,
        "generated_at": _utc_now_iso(),
    }

    preview_by_endpoint[cache_key] = preview_payload
    payload["preview_by_endpoint"] = preview_by_endpoint
    _store_diff_payload(job_id, payload)
    return preview_payload


@app.route("/goto")
def goto():
    username = session.get("username")
    tab = request.args.get("tab")

    if not username:
        return redirect(url_for("login", referrer="/goto?tab=" + str(tab)))

    perms = _user_permissions(username)

    if tab == "rollback-queue":
        return redirect("/rollback-queue")

    if tab == "rollback-batch":
        if "rollback_batch" not in perms:
            abort(403)
        return redirect("/rollback_batch")

    if tab == "rollback-all-jobs":
        if "read_all" not in _user_permissions(username) and not is_admin_user(
            username
        ):
            abort(403)
        return redirect("/rollback-queue/all-jobs")

    if tab == "rollback-from-diff":
        return redirect("/rollback-from-diff")

    if tab == "rollback-account":
        return redirect("/rollback-account")

    if tab == "rollback-requests":
        return redirect("/rollback-requests")

    if tab == "rollback-config":
        if not _can_view_runtime_config(username):
            abort(403)
        return redirect("/rollback-config")

    if tab == "modules":
        if not (is_maintainer(username) or is_admin_user(username)):
            abort(403)
        return redirect("/modules")

    if tab == "documentation":
        return redirect(DOCS_URL)

    return redirect("/rollback-queue")


@app.route("/api/v1/rollback/worker")
def worker_status():
    hb = r.get(WORKER_HEARTBEAT_KEY)

    if not hb:
        return jsonify({"status": "offline"})

    age = time.time() - float(hb)

    return jsonify(
        {
            "status": "online",
            "last_seen": age,
        }
    )


@app.route("/api/v1/rollback/jobs/progress")
def batch_job_progress():
    if session.get("username") is None:
        return jsonify({"detail": "Not authenticated"}), 401

    ids = request.args.get("ids", "")

    if not ids:
        return jsonify({"jobs": []})

    job_ids = [int(x) for x in ids.split(",") if x.strip()]

    jobs = []

    for jid in job_ids:
        p = get_progress(jid)

        if p:
            jobs.append(
                {
                    "id": jid,
                    **p,
                }
            )

    return jsonify({"jobs": jobs})


@app.route("/rollback-queue")
def rollback_queue_ui():
    username = session.get("username")

    jobs = []

    if username:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, requested_by, status, dry_run, created_at
                    FROM rollback_jobs
                    WHERE requested_by=%s
                      AND (
                        status NOT IN ('completed', 'failed', 'canceled')
                        OR (status='failed' AND created_at >= (NOW() - INTERVAL 24 HOUR))
                                                OR (status='completed' AND created_at >= (NOW() - INTERVAL 2 HOUR))
                      )
                    ORDER BY id DESC
                    LIMIT 100
                    """,
                    (username,),
                )

                jobs = cursor.fetchall()

    return render_template(
        "rollback_queue.html",
        jobs=jobs,
        username=username,
        is_maintainer=bool(username and is_maintainer(username)),
        type="rollback-queue",
    )


@app.route("/api/v1/rollback/from-diff", methods=["POST"])
def rollback_from_diff_api():
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    perms = _user_permissions(username)

    _has_submit_right = (
        "write" in perms or "rollback_diff" in perms or "from_diff" in perms
    )
    if not _has_submit_right:
        return jsonify({"detail": "Forbidden"}), 403

    if not _check_rate_limit(username):
        return jsonify({"detail": "Rate limit exceeded; try again later"}), 429

    payload = request.get_json(silent=True) or {}

    diff = request.args.get("diff") or payload.get("diff") or request.form.get("diff")
    summary = (
        request.args.get("summary")
        or payload.get("summary")
        or request.form.get("summary")
        or ""
    )
    dry_run_raw = (
        request.args.get("dry_run")
        if request.args.get("dry_run") is not None
        else payload.get("dry_run", request.form.get("dry_run"))
    )
    limit_raw = (
        request.args.get("limit")
        if request.args.get("limit") is not None
        else payload.get("limit", request.form.get("limit"))
    )

    if diff in (None, ""):
        return jsonify({"detail": "Missing required parameter: diff"}), 400

    limit = None

    if limit_raw not in (None, ""):
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            return jsonify({"detail": "limit must be an integer"}), 400

        if limit <= 0:
            return jsonify({"detail": "limit must be a positive integer"}), 400

        if limit > 10000:
            return jsonify({"detail": "limit must be <= 10000"}), 400

    dry_run = _parse_bool(dry_run_raw, default=False)

    _dry_run_only = (
        "rollback_diff_dry_run_only" in perms or "from_diff_dry_run_only" in perms
    )
    if _dry_run_only and not dry_run:
        return jsonify(
            {"detail": "Forbidden: from-diff access is limited to dry-run mode"}
        ), 403

    batch_id = int(time.time() * 1000)
    autoapproved = False

    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO rollback_jobs
                    (
                        requested_by,
                        status,
                        dry_run,
                        batch_id,
                        request_type,
                        requested_endpoint,
                        approved_endpoint,
                        approval_required
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        username,
                        _REQUEST_STATUS_PENDING_APPROVAL,
                        1 if dry_run else 0,
                        batch_id,
                        _REQUEST_TYPE_DIFF,
                        _ENDPOINT_FROM_DIFF,
                        None,
                        _APPROVAL_REQUIRED_MAINTAINER,
                    ),
                )
                job_id = cursor.lastrowid

                autoapproved = _should_autoapprove_request(
                    username,
                    _APPROVAL_REQUIRED_MAINTAINER,
                )
                if autoapproved:
                    cursor.execute(
                        """
                        UPDATE rollback_jobs
                        SET
                            status=%s,
                            approved_endpoint=%s,
                            approved_by=%s,
                            approved_at=CURRENT_TIMESTAMP
                        WHERE id=%s
                        """,
                        ("resolving", _ENDPOINT_FROM_DIFF, username, job_id),
                    )
            conn.commit()

        _store_diff_payload(
            job_id,
            {
                "diff": diff,
                "summary": summary,
                "requested_by": username,
                "dry_run": dry_run,
                "limit": limit,
                "requested_endpoint": _ENDPOINT_FROM_DIFF,
                "approved_endpoint": _ENDPOINT_FROM_DIFF if autoapproved else None,
                "approved_by": username if autoapproved else None,
                "approved_at": _utc_now_iso() if autoapproved else None,
            },
        )

        if autoapproved:
            _set_diff_error(job_id, None)
            status_updater.update_wiki_status(
                editing="Resolving diff",
                current_job=f"Auto-approved diff job {job_id} resolving",
            )
            resolve_diff_rollback_job.delay(job_id)
    except Exception as e:
        logging.exception("Error in rollback_from_diff_api")
        return jsonify({"detail": "Failed to create rollback jobs: " + str(e)}), 500

    return jsonify(
        {
            "job_id": job_id,
            "job_ids": [job_id],
            "chunks": 1,
            "batch_id": batch_id,
            "total_items": 0,
            "status": "resolving" if autoapproved else _REQUEST_STATUS_PENDING_APPROVAL,
            "diff": diff,
            "dry_run": dry_run,
            "limit": limit,
            "request_type": _REQUEST_TYPE_DIFF,
            "requested_endpoint": _ENDPOINT_FROM_DIFF,
            "approved_endpoint": _ENDPOINT_FROM_DIFF if autoapproved else None,
            "approved_by": username if autoapproved else None,
            "approval_required": _APPROVAL_REQUIRED_MAINTAINER,
        }
    )


@app.route("/api/v1/rollback/from-account", methods=["POST"])
def rollback_from_account_api():
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    perms = _user_permissions(username)

    _has_submit_right = (
        "write" in perms or "rollback_account" in perms or "from_diff" in perms
    )
    if not _has_submit_right:
        return jsonify({"detail": "Forbidden"}), 403

    if not _check_rate_limit(username):
        return jsonify({"detail": "Rate limit exceeded; try again later"}), 429

    payload = request.get_json(silent=True) or {}

    target_user_raw = (
        request.args.get("target_user")
        if request.args.get("target_user") is not None
        else payload.get("target_user", request.form.get("target_user"))
    )
    if target_user_raw in (None, ""):
        target_user_raw = (
            request.args.get("user")
            if request.args.get("user") is not None
            else payload.get("user", request.form.get("user"))
        )
    if target_user_raw in (None, ""):
        target_user_raw = (
            request.args.get("account")
            if request.args.get("account") is not None
            else payload.get("account", request.form.get("account"))
        )

    summary = (
        request.args.get("summary")
        or payload.get("summary")
        or request.form.get("summary")
        or ""
    )
    dry_run_raw = (
        request.args.get("dry_run")
        if request.args.get("dry_run") is not None
        else payload.get("dry_run", request.form.get("dry_run"))
    )
    limit_raw = (
        request.args.get("limit")
        if request.args.get("limit") is not None
        else payload.get("limit", request.form.get("limit"))
    )

    target_user = _normalize_target_user_input(target_user_raw)
    if not target_user:
        return jsonify({"detail": "Missing required parameter: target_user"}), 400

    if len(target_user) > 85:
        return jsonify({"detail": "target_user is too long"}), 400

    dry_run = _parse_bool(dry_run_raw, default=False)

    _dry_run_only = (
        "rollback_diff_dry_run_only" in perms or "from_diff_dry_run_only" in perms
    )
    if _dry_run_only and not dry_run:
        return jsonify(
            {"detail": "Forbidden: from-diff access is limited to dry-run mode"}
        ), 403

    limit = _ACCOUNT_ROLLBACK_MAX_LIMIT
    if limit_raw not in (None, ""):
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            return jsonify({"detail": "limit must be an integer"}), 400

        if limit <= 0:
            return jsonify({"detail": "limit must be a positive integer"}), 400

        if limit > _ACCOUNT_ROLLBACK_MAX_LIMIT:
            return jsonify(
                {"detail": f"limit must be <= {_ACCOUNT_ROLLBACK_MAX_LIMIT}"}
            ), 400

    try:
        batch_id = int(time.time() * 1000)
        autoapproved = False

        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO rollback_jobs
                    (
                        requested_by,
                        status,
                        dry_run,
                        batch_id,
                        request_type,
                        requested_endpoint,
                        approved_endpoint,
                        approval_required
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        username,
                        _REQUEST_STATUS_PENDING_APPROVAL,
                        1 if dry_run else 0,
                        batch_id,
                        _REQUEST_TYPE_DIFF,
                        _ENDPOINT_FROM_ACCOUNT,
                        None,
                        _APPROVAL_REQUIRED_MAINTAINER,
                    ),
                )
                job_id = cursor.lastrowid

                autoapproved = _should_autoapprove_request(
                    username,
                    _APPROVAL_REQUIRED_MAINTAINER,
                )
                if autoapproved:
                    cursor.execute(
                        """
                        UPDATE rollback_jobs
                        SET
                            status=%s,
                            approved_endpoint=%s,
                            approved_by=%s,
                            approved_at=CURRENT_TIMESTAMP
                        WHERE id=%s
                        """,
                        ("resolving", _ENDPOINT_FROM_ACCOUNT, username, job_id),
                    )
            conn.commit()

        _store_diff_payload(
            job_id,
            {
                "target_user": target_user,
                "summary": summary,
                "requested_by": username,
                "dry_run": dry_run,
                "limit": limit,
                "requested_endpoint": _ENDPOINT_FROM_ACCOUNT,
                "approved_endpoint": _ENDPOINT_FROM_ACCOUNT if autoapproved else None,
                "approved_by": username if autoapproved else None,
                "approved_at": _utc_now_iso() if autoapproved else None,
            },
        )

        if autoapproved:
            _set_diff_error(job_id, None)
            status_updater.update_wiki_status(
                editing="Resolving account",
                current_job=f"Auto-approved account job {job_id} resolving",
            )
            resolve_diff_rollback_job.delay(job_id)

    except ValueError as e:
        return jsonify({"detail": str(e)}), 400
    except Exception as e:
        logging.exception("Error in rollback_from_account_api")
        return jsonify({"detail": "Failed to create rollback jobs: " + str(e)}), 500

    return jsonify(
        {
            "job_id": job_id,
            "job_ids": [job_id],
            "chunks": 1,
            "batch_id": batch_id,
            "total_items": 0,
            "status": "resolving" if autoapproved else _REQUEST_STATUS_PENDING_APPROVAL,
            "resolved_user": target_user,
            "dry_run": dry_run,
            "limit": limit,
            "request_type": _REQUEST_TYPE_DIFF,
            "requested_endpoint": _ENDPOINT_FROM_ACCOUNT,
            "approved_endpoint": _ENDPOINT_FROM_ACCOUNT if autoapproved else None,
            "approved_by": username if autoapproved else None,
            "approval_required": _APPROVAL_REQUIRED_MAINTAINER,
        }
    )


@app.route("/rollback-from-diff")
def rollback_from_diff_page():
    username = session.get("username")

    if not username:
        abort(401)

    perms = _user_permissions(username)

    if "rollback_diff" not in perms:
        abort(403)

    return render_template(
        "rollback_from_diff.html",
        username=username,
        max_limit=10000,
        default_limit=100,
        from_diff_dry_run_only=bool("rollback_diff_dry_run_only" in perms),
        type="rollback-from-diff",
    )


@app.route("/rollback-account")
def rollback_account_page():
    username = session.get("username")

    if not username:
        abort(401)

    perms = _user_permissions(username)

    if "rollback_account" not in perms:
        abort(403)

    return render_template(
        "rollback_account.html",
        username=username,
        max_limit=_ACCOUNT_ROLLBACK_MAX_LIMIT,
        default_limit=_ACCOUNT_ROLLBACK_MAX_LIMIT,
        from_diff_dry_run_only=bool("rollback_diff_dry_run_only" in perms),
        type="rollback-account",
    )


@app.route("/rollback-requests")
def rollback_requests_page():
    username = session.get("username")

    if not username:
        abort(401)

    can_review = _can_review_requests(username)

    return render_template(
        "rollback_requests.html",
        username=username,
        can_review_all_requests=bool(can_review),
        can_approve_diff=bool(is_maintainer(username)),
        can_approve_batch=bool(can_review),
        type="rollback-requests",
    )


@app.route("/api/v1/rollback/requests", methods=["GET"])
def list_rollback_requests_api():
    username = session.get("username")
    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    can_review = _can_review_requests(username)
    requested_by_filter = request.args.get("requested_by")
    status_filter = request.args.get("status")

    where_parts = ["j.request_type IN (%s, %s)"]
    params = [_REQUEST_TYPE_DIFF, _REQUEST_TYPE_BATCH]

    if status_filter:
        where_parts.append("j.status=%s")
        params.append(status_filter)

    if requested_by_filter:
        if (
            not can_review
            and requested_by_filter.strip().lower() != username.strip().lower()
        ):
            return jsonify({"detail": "Forbidden"}), 403
        where_parts.append("j.requested_by=%s")
        params.append(requested_by_filter)
    elif not can_review:
        where_parts.append("j.requested_by=%s")
        params.append(username)

    where_sql = " AND ".join(where_parts)

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    j.id,
                    j.batch_id,
                    j.requested_by,
                    j.status,
                    j.dry_run,
                    j.created_at,
                    j.request_type,
                    j.requested_endpoint,
                    j.approved_endpoint,
                    j.approval_required,
                    j.approved_by,
                    j.approved_at,
                    COUNT(i.id) AS total_items,
                    COALESCE(SUM(CASE WHEN i.status='completed' THEN 1 ELSE 0 END), 0) AS completed_items,
                    COALESCE(SUM(CASE WHEN i.status='failed' THEN 1 ELSE 0 END), 0) AS failed_items
                FROM rollback_jobs j
                LEFT JOIN rollback_job_items i ON i.job_id = j.id
                WHERE {where_sql}
                GROUP BY
                    j.id,
                    j.batch_id,
                    j.requested_by,
                    j.status,
                    j.dry_run,
                    j.created_at,
                    j.request_type,
                    j.requested_endpoint,
                    j.approved_endpoint,
                    j.approval_required,
                    j.approved_by,
                    j.approved_at
                ORDER BY j.id DESC
                LIMIT 500
                """,
                tuple(params),
            )
            rows = cursor.fetchall()

    requests_payload = []
    for row in rows:
        (
            job_id,
            batch_id,
            requested_by,
            status,
            dry_run,
            created_at,
            request_type,
            requested_endpoint,
            approved_endpoint,
            approval_required,
            approved_by,
            approved_at,
            total,
            completed,
            failed,
        ) = row

        requests_payload.append(
            {
                "id": int(job_id),
                "batch_id": int(batch_id) if batch_id is not None else None,
                "requested_by": requested_by,
                "status": status,
                "dry_run": bool(dry_run),
                "created_at": str(created_at),
                "request_type": request_type,
                "requested_endpoint": requested_endpoint,
                "approved_endpoint": approved_endpoint,
                "approval_required": approval_required,
                "approved_by": approved_by,
                "approved_at": str(approved_at) if approved_at else None,
                "total": int(total or 0),
                "completed": int(completed or 0),
                "failed": int(failed or 0),
            }
        )

    return jsonify(
        {
            "requests": requests_payload,
            "can_review_all_requests": bool(can_review),
            "can_approve_diff": bool(is_maintainer(username)),
            "can_approve_batch": bool(can_review),
        }
    )


@app.route("/api/v1/rollback/requests/<int:job_id>/preview", methods=["GET"])
def rollback_request_preview_api(job_id: int):
    username = session.get("username")
    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    requested_endpoint = _normalize_request_endpoint(request.args.get("endpoint"))
    full_from_diff = _parse_bool(request.args.get("full"), default=True)

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, requested_by, request_type, requested_endpoint
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )
            row = cursor.fetchone()

            if not row:
                return jsonify({"detail": "Request not found"}), 404

            _, requested_by, request_type, stored_endpoint = row

            if requested_by != username and not _can_review_requests(username):
                return jsonify({"detail": "Forbidden"}), 403

            request_type = _normalize_request_type(request_type)

            if request_type == _REQUEST_TYPE_BATCH:
                cursor.execute(
                    """
                    SELECT file_title, target_user, summary, status, error
                    FROM rollback_job_items
                    WHERE job_id=%s
                    ORDER BY id ASC
                    """,
                    (job_id,),
                )
                items = cursor.fetchall()

                preview_items = [
                    {
                        "title": item[0],
                        "user": item[1],
                        "summary": item[2],
                        "status": item[3],
                        "error": item[4],
                    }
                    for item in items
                ]

                return jsonify(
                    {
                        "job_id": job_id,
                        "request_type": request_type,
                        "endpoint": _ENDPOINT_BATCH,
                        "total_items": len(preview_items),
                        "items": preview_items,
                    }
                )

    if request_type != _REQUEST_TYPE_DIFF:
        return jsonify({"detail": f"Unsupported request_type: {request_type}"}), 400

    payload = _load_diff_payload(job_id)
    if not payload:
        return jsonify({"detail": "Missing request payload"}), 404

    endpoint = requested_endpoint or _normalize_request_endpoint(
        stored_endpoint or payload.get("requested_endpoint") or _ENDPOINT_FROM_DIFF
    )
    if endpoint not in _ALLOWED_DIFF_REQUEST_ENDPOINTS:
        return jsonify({"detail": "Invalid endpoint"}), 400

    if endpoint == _ENDPOINT_FROM_DIFF and not _request_payload_has_diff_anchor(
        payload
    ):
        return jsonify(
            {
                "detail": "This request does not include a diff anchor for endpoint=from_diff"
            }
        ), 400

    try:
        preview = _compute_diff_request_preview(
            job_id,
            payload,
            endpoint,
            full_from_diff=full_from_diff,
        )
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Failed to compute request preview for job %s", job_id)
        return jsonify({"detail": f"Failed to compute request preview: {exc}"}), 500

    return jsonify(
        {
            "job_id": job_id,
            "request_type": request_type,
            **preview,
        }
    )


@app.route("/rollback-queue/all-jobs")
def rollback_queue_all_jobs_ui():
    username = session.get("username")

    if not username:
        abort(401)

    if "read_all" not in _user_permissions(username) and not is_admin_user(username):
        abort(403)

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    j.id,
                    j.batch_id,
                    j.requested_by,
                    j.status,
                    j.dry_run,
                    j.created_at,
                    j.request_type,
                    j.requested_endpoint,
                    j.approved_endpoint,
                    j.approval_required,
                    j.approved_by,
                    j.approved_at,
                    COUNT(i.id) AS total_items,
                    COALESCE(SUM(CASE WHEN i.status='completed' THEN 1 ELSE 0 END), 0) AS completed_items,
                    COALESCE(SUM(CASE WHEN i.status='failed' THEN 1 ELSE 0 END), 0) AS failed_items
                FROM rollback_jobs j
                LEFT JOIN rollback_job_items i ON i.job_id = j.id
                GROUP BY
                    j.id,
                    j.batch_id,
                    j.requested_by,
                    j.status,
                    j.dry_run,
                    j.created_at,
                    j.request_type,
                    j.requested_endpoint,
                    j.approved_endpoint,
                    j.approval_required,
                    j.approved_by,
                    j.approved_at
                ORDER BY COALESCE(j.batch_id, j.id) DESC, j.id DESC
                """
            )

            jobs = cursor.fetchall()

    if request.args.get("format") == "json":
        jobs_for_output = []
        for row in jobs:
            if len(row) >= 15:
                (
                    job_id,
                    batch_id,
                    requested_by,
                    status,
                    dry_run,
                    created_at,
                    request_type,
                    requested_endpoint,
                    approved_endpoint,
                    approval_required,
                    approved_by,
                    approved_at,
                    total,
                    completed,
                    failed,
                ) = row
            else:
                (
                    job_id,
                    batch_id,
                    requested_by,
                    status,
                    dry_run,
                    created_at,
                    total,
                    completed,
                    failed,
                ) = row
                request_type = None
                requested_endpoint = None
                approved_endpoint = None
                approval_required = None
                approved_by = None
                approved_at = None
            if _maybe_mark_stale_resolving_job_failed(job_id, status, created_at):
                status = "failed"

            # Some legacy rows may store non-numeric batch identifiers.
            # Keep the endpoint resilient by treating unparseable values as null.
            normalized_batch_id = None
            if batch_id is not None:
                try:
                    normalized_batch_id = int(batch_id)
                except (TypeError, ValueError):
                    normalized_batch_id = None

            jobs_for_output.append(
                {
                    "id": job_id,
                    "batch_id": normalized_batch_id,
                    "requested_by": requested_by,
                    "status": status,
                    "dry_run": bool(dry_run),
                    "created_at": str(created_at),
                    "request_type": request_type,
                    "requested_endpoint": requested_endpoint,
                    "approved_endpoint": approved_endpoint,
                    "approval_required": approval_required,
                    "approved_by": approved_by,
                    "approved_at": str(approved_at) if approved_at else None,
                    "total": int(total or 0),
                    "completed": int(completed or 0),
                    "failed": int(failed or 0),
                }
            )

        return jsonify({"jobs": jobs_for_output})

    return render_template(
        "rollback_queue_all_jobs.html",
        jobs=jobs,
        username=username,
        can_approve_diff=bool(is_maintainer(username)),
        can_approve_batch=bool(is_maintainer(username) or is_admin_user(username)),
        type="rollback-all-jobs",
    )


@app.route("/rollback_batch")
def rollback_batch():
    username = session.get("username")

    if not username:
        abort(401)

    if "rollback_batch" not in _user_permissions(username):
        abort(403)

    return render_template(
        "batch_rollback.html",
        username=username,
        type="batch-rollback",
    )


@app.route("/rollback-config")
def rollback_config_ui():
    username = session.get("username")

    if not username:
        abort(401)

    if not _can_view_runtime_config(username):
        abort(403)

    return render_template(
        "runtime_config.html",
        username=username,
        can_edit_config=_can_edit_runtime_config(username),
        type="runtime-config",
    )


@app.route("/modules")
def modules_ui():
    username = session.get("username")

    if not username:
        abort(401)

    if not (is_maintainer(username) or is_admin_user(username)):
        abort(403)

    return render_template(
        "modules.html",
        username=username,
        is_maintainer=is_maintainer(username),
        is_bot_admin=is_admin_user(username),
        type="modules",
    )


@app.route("/api/v1/config/authz", methods=["GET"])
def get_runtime_authz_api():
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    if not _can_view_runtime_config(username):
        return jsonify({"detail": "Forbidden"}), 403

    config = _effective_runtime_authz_config()
    return jsonify(
        {
            "config": _serialize_runtime_authz_config(config),
            "can_edit": _can_edit_runtime_config(username),
            "can_manage_user_grants": _can_manage_user_grants(username),
            "editable_keys": _RUNTIME_AUTHZ_ALLOWED_KEYS,
            "grant_groups": sorted(_USER_GRANT_GROUPS.keys()),
            "grant_rights": sorted(_USER_GRANT_RIGHTS),
            "auto_grant_roles": sorted(_AUTO_GRANT_ROLE_KEYS),
        }
    )


@app.route("/api/v1/config/authz", methods=["PUT"])
def update_runtime_authz_api():
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    if not _can_edit_runtime_config(username):
        return jsonify({"detail": "Forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"detail": "Invalid payload"}), 400

    updates = payload.get("config", payload)
    if not isinstance(updates, dict):
        return jsonify({"detail": "config must be an object"}), 400

    normalized_updates, errors = _normalize_runtime_authz_updates(updates)
    if errors:
        return jsonify({"detail": "; ".join(errors)}), 400

    if not normalized_updates:
        return jsonify({"detail": "No valid config keys supplied"}), 400

    _persist_runtime_authz_updates(normalized_updates, updated_by=username)
    effective = _effective_runtime_authz_config()

    return jsonify(
        {
            "ok": True,
            "config": _serialize_runtime_authz_config(effective),
            "can_edit": _can_edit_runtime_config(username),
            "can_manage_user_grants": _can_manage_user_grants(username),
            "editable_keys": _RUNTIME_AUTHZ_ALLOWED_KEYS,
            "grant_groups": sorted(_USER_GRANT_GROUPS.keys()),
            "grant_rights": sorted(_USER_GRANT_RIGHTS),
            "auto_grant_roles": sorted(_AUTO_GRANT_ROLE_KEYS),
        }
    )


@app.route("/api/v1/config/authz/user-grants/<path:target_username>", methods=["GET"])
def get_runtime_authz_user_grants(target_username: str):
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    if not _can_manage_user_grants(username):
        return jsonify({"detail": "Forbidden"}), 403

    normalized_target = _normalize_username(target_username)
    if not normalized_target:
        return jsonify({"detail": "Username is required"}), 400

    refresh_commons = _parse_bool(request.args.get("refresh_commons"), default=False)

    config = _effective_runtime_authz_config()
    commons_groups = set(
        get_user_groups(normalized_target, force_refresh=refresh_commons)
    )
    payload = _get_user_grants_payload(
        normalized_target, config, commons_groups=commons_groups
    )
    payload["implicit_flag_order"] = list(_USER_IMPLICIT_FLAGS)
    payload["grant_groups"] = sorted(_USER_GRANT_GROUPS.keys())
    payload["grant_rights"] = sorted(_USER_GRANT_RIGHTS)
    payload["can_edit"] = _can_manage_user_grants(username)
    payload["commons_groups_refreshed"] = bool(refresh_commons)
    return jsonify(payload)


@app.route("/api/v1/config/authz/user-grants/<path:target_username>", methods=["PUT"])
def update_runtime_authz_user_grants(target_username: str):
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    if not _can_manage_user_grants(username):
        return jsonify({"detail": "Forbidden"}), 403

    normalized_target = _normalize_username(target_username)
    if not normalized_target:
        return jsonify({"detail": "Username is required"}), 400

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"detail": "Invalid payload"}), 400

    groups = payload.get("groups", [])
    rights = payload.get("rights", [])

    if groups is None:
        groups = []
    if rights is None:
        rights = []

    normalized_entry, errors = _normalize_runtime_authz_updates(
        {
            "USER_GRANTS_JSON": {
                normalized_target: {
                    "groups": groups,
                    "rights": rights,
                }
            }
        }
    )

    if errors:
        return jsonify({"detail": "; ".join(errors)}), 400

    config = _effective_runtime_authz_config()
    grants_map = dict(config.get("USER_GRANTS_JSON") or {})

    user_map = normalized_entry.get("USER_GRANTS_JSON", {})
    if normalized_target in user_map:
        grants_map[normalized_target] = user_map[normalized_target]
    else:
        grants_map.pop(normalized_target, None)

    _persist_runtime_authz_updates(
        {"USER_GRANTS_JSON": grants_map}, updated_by=username
    )
    updated_config = _effective_runtime_authz_config()
    response_payload = _get_user_grants_payload(normalized_target, updated_config)
    response_payload["ok"] = True
    response_payload["can_edit"] = _can_manage_user_grants(username)
    return jsonify(response_payload)


@app.route("/api/v1/rollback/jobs", methods=["GET"])
def list_rollback_jobs():
    username = session.get("username")
    if username is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    requested_by,
                    status,
                    dry_run,
                    created_at,
                    request_type,
                    requested_endpoint,
                    approved_endpoint,
                    approval_required,
                    approved_by,
                    approved_at
                FROM rollback_jobs
                WHERE requested_by=%s
                                    AND (
                                        status NOT IN ('completed', 'failed', 'canceled')
                                        OR (status='failed' AND created_at >= (NOW() - INTERVAL 24 HOUR))
                                        OR (status='completed' AND created_at >= (NOW() - INTERVAL 2 HOUR))
                                    )
                ORDER BY id DESC
                LIMIT 100
                """,
                (username,),
            )

            jobs = cursor.fetchall()

    return jsonify(
        {
            "jobs": [
                {
                    "id": row[0],
                    "requested_by": row[1],
                    "status": row[2],
                    "dry_run": bool(row[3]),
                    "created_at": str(row[4]),
                    "request_type": row[5] if len(row) > 5 else None,
                    "requested_endpoint": row[6] if len(row) > 6 else None,
                    "approved_endpoint": row[7] if len(row) > 7 else None,
                    "approval_required": row[8] if len(row) > 8 else None,
                    "approved_by": row[9] if len(row) > 9 else None,
                    "approved_at": (
                        str(row[10]) if len(row) > 10 and row[10] else None
                    ),
                }
                for row in jobs
            ]
        }
    )


@app.route("/api/v1/rollback/jobs", methods=["POST"])
def create_rollback_job():
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    perms = _user_permissions(actor)

    if "write" not in perms:
        return jsonify({"detail": "Forbidden: write access required"}), 403

    if not _check_rate_limit(actor):
        return jsonify({"detail": "Rate limit exceeded; try again later"}), 429

    payload = request.get_json(silent=True) or {}

    requested_by = payload.get("requested_by") or actor
    items = payload.get("items") or payload.get("files") or []
    dry_run = _parse_bool(payload.get("dry_run", False), default=False)
    request_type = _normalize_request_type(payload.get("request_type"))

    if request_type == _REQUEST_TYPE_BATCH and "rollback_batch" not in perms:
        return jsonify({"detail": "Forbidden: rollback_batch right required"}), 403

    raw_batch_id = payload.get("batch_id")

    if raw_batch_id in (None, ""):
        batch_id = int(time.time() * 1000)
    else:
        try:
            batch_id = int(raw_batch_id)
        except (TypeError, ValueError):
            return jsonify({"detail": "batch_id must be an integer"}), 400

        if batch_id <= 0:
            return jsonify({"detail": "batch_id must be a positive integer"}), 400

    if requested_by != actor:
        return jsonify({"detail": "requested_by must match authenticated user"}), 403

    if not isinstance(items, list) or len(items) == 0:
        return jsonify({"detail": "items must be a non-empty list"}), 400

    if len(items) > 1000:
        return jsonify({"detail": "Too many rollback items"}), 400

    requested_endpoint = (
        _ENDPOINT_BATCH if request_type == _REQUEST_TYPE_BATCH else _REQUEST_TYPE_QUEUE
    )
    approval_required = _approval_requirement_for_request(
        request_type, requested_endpoint
    )
    initial_status = (
        _REQUEST_STATUS_PENDING_APPROVAL
        if request_type == _REQUEST_TYPE_BATCH
        else "queued"
    )
    item_initial_status = (
        _REQUEST_STATUS_PENDING_APPROVAL
        if request_type == _REQUEST_TYPE_BATCH
        else "queued"
    )

    job_ids = []

    with get_conn() as conn:
        with conn.cursor() as cursor:
            for i in range(0, len(items), MAX_JOB_ITEMS()):
                chunk = items[i : i + MAX_JOB_ITEMS()]

                cursor.execute(
                    """
                    INSERT INTO rollback_jobs
                    (
                        requested_by,
                        status,
                        dry_run,
                        batch_id,
                        request_type,
                        requested_endpoint,
                        approved_endpoint,
                        approval_required
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        requested_by,
                        initial_status,
                        1 if dry_run else 0,
                        batch_id,
                        request_type,
                        requested_endpoint,
                        None,
                        approval_required,
                    ),
                )

                job_id = cursor.lastrowid
                job_ids.append(job_id)

                for item in chunk:
                    title = (item.get("title") or item.get("file") or "").strip()
                    user = (item.get("user") or "").strip()
                    summary = item.get("summary")

                    if not title or not user:
                        continue

                    cursor.execute(
                        """
                        INSERT INTO rollback_job_items
                        (job_id, file_title, target_user, summary, status)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (job_id, title, user, summary, item_initial_status),
                    )

        conn.commit()

    if not job_ids:
        return jsonify({"detail": "No valid items to process"}), 400

    if request_type != _REQUEST_TYPE_BATCH:
        for jid in job_ids:
            process_rollback_job.delay(jid)

    return jsonify(
        {
            "job_id": job_ids[0],
            "status": initial_status,
            "batch_id": batch_id,
            "job_ids": job_ids,
            "chunks": len(job_ids),
            "request_type": request_type,
            "requested_endpoint": requested_endpoint,
            "approval_required": approval_required,
        }
    )


@app.route("/api/v1/rollback/jobs/<int:job_id>/approve", methods=["POST"])
def approve_rollback_job(job_id: int):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    payload = request.get_json(silent=True) or {}
    endpoint_override = _normalize_request_endpoint(payload.get("endpoint"))

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    requested_by,
                    status,
                    dry_run,
                    batch_id,
                    request_type,
                    requested_endpoint,
                    approved_endpoint,
                    approval_required
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )
            job = cursor.fetchone()

            if not job:
                return jsonify({"detail": "Job not found"}), 404

            (
                _id,
                requested_by,
                status,
                dry_run,
                batch_id,
                request_type,
                requested_endpoint,
                approved_endpoint,
                approval_required,
            ) = job

            request_type = _normalize_request_type(request_type)
            requested_endpoint = _normalize_request_endpoint(requested_endpoint)
            approval_required = approval_required or _approval_requirement_for_request(
                request_type, requested_endpoint
            )

            if not approval_required:
                return jsonify({"detail": "This job does not require approval"}), 400

            if status != _REQUEST_STATUS_PENDING_APPROVAL:
                return jsonify(
                    {"detail": f"Job is not pending approval (status={status})"}
                ), 409

            if not _can_actor_approve(actor, approval_required):
                return jsonify(
                    {"detail": "Forbidden: insufficient approval rights"}
                ), 403

            approved_endpoint = endpoint_override or requested_endpoint

            if request_type == _REQUEST_TYPE_DIFF:
                if approved_endpoint not in _ALLOWED_DIFF_REQUEST_ENDPOINTS:
                    return jsonify(
                        {
                            "detail": (
                                "endpoint must be one of: "
                                + ", ".join(sorted(_ALLOWED_DIFF_REQUEST_ENDPOINTS))
                            )
                        }
                    ), 400

                if approved_endpoint == _ENDPOINT_FROM_DIFF:
                    request_payload = _load_diff_payload(job_id)
                    if not _request_payload_has_diff_anchor(request_payload):
                        return jsonify(
                            {
                                "detail": "This request does not include a diff anchor for endpoint=from_diff"
                            }
                        ), 400

                cursor.execute(
                    """
                    UPDATE rollback_jobs
                    SET
                        status=%s,
                        approved_endpoint=%s,
                        approved_by=%s,
                        approved_at=CURRENT_TIMESTAMP
                    WHERE id=%s
                    """,
                    ("resolving", approved_endpoint, actor, job_id),
                )
                conn.commit()

                _update_diff_payload(
                    job_id,
                    {
                        "approved_endpoint": approved_endpoint,
                        "approved_by": actor,
                        "approved_at": _utc_now_iso(),
                    },
                )
                _set_diff_error(job_id, None)

                status_updater.update_wiki_status(
                    editing="Resolving diff",
                    current_job=f"Approved diff job {job_id} resolving",
                )

                resolve_diff_rollback_job.delay(job_id)

                return jsonify(
                    {
                        "job_id": job_id,
                        "requested_by": requested_by,
                        "approved_by": actor,
                        "approved_endpoint": approved_endpoint,
                        "dry_run": bool(dry_run),
                        "status": "resolving",
                    }
                )

            if request_type != _REQUEST_TYPE_BATCH:
                return jsonify(
                    {"detail": f"Unsupported request_type: {request_type}"}
                ), 400

            if approved_endpoint not in (None, "", _ENDPOINT_BATCH):
                return jsonify(
                    {"detail": "Batch requests can only use endpoint=batch"}
                ), 400

            approved_job_ids = []

            if batch_id is not None:
                cursor.execute(
                    """
                    SELECT id
                    FROM rollback_jobs
                    WHERE batch_id=%s AND request_type=%s AND status=%s
                    ORDER BY id ASC
                    """,
                    (batch_id, _REQUEST_TYPE_BATCH, _REQUEST_STATUS_PENDING_APPROVAL),
                )
                approved_job_ids = [int(row[0]) for row in cursor.fetchall()]

            if not approved_job_ids:
                approved_job_ids = [job_id]

            for approved_job_id in approved_job_ids:
                cursor.execute(
                    """
                    UPDATE rollback_jobs
                    SET
                        status=%s,
                        approved_endpoint=%s,
                        approved_by=%s,
                        approved_at=CURRENT_TIMESTAMP
                    WHERE id=%s
                    """,
                    ("queued", _ENDPOINT_BATCH, actor, approved_job_id),
                )
                cursor.execute(
                    """
                    UPDATE rollback_job_items
                    SET status=%s
                    WHERE job_id=%s AND status=%s
                    """,
                    ("queued", approved_job_id, _REQUEST_STATUS_PENDING_APPROVAL),
                )

        conn.commit()

    status_updater.update_wiki_status(
        editing="Actively editing",
        current_job=f"Processing approved batch job {job_id} with {len(approved_job_ids)} job(s)",
    )

    for approved_job_id in approved_job_ids:
        process_rollback_job.delay(approved_job_id)

    return jsonify(
        {
            "job_id": job_id,
            "batch_id": batch_id,
            "approved_job_ids": approved_job_ids,
            "approved_by": actor,
            "approved_endpoint": _ENDPOINT_BATCH,
            "status": "queued",
        }
    )


@app.route("/api/v1/rollback/jobs/<int:job_id>/reject", methods=["POST"])
def reject_rollback_request(job_id: int):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    requested_by,
                    status,
                    batch_id,
                    request_type,
                    requested_endpoint,
                    approval_required
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )
            row = cursor.fetchone()

            if not row:
                return jsonify({"detail": "Job not found"}), 404

            (
                _id,
                _requested_by,
                status,
                batch_id,
                request_type,
                requested_endpoint,
                approval_required,
            ) = row

            request_type = _normalize_request_type(request_type)
            requested_endpoint = _normalize_request_endpoint(requested_endpoint)
            approval_required = approval_required or _approval_requirement_for_request(
                request_type, requested_endpoint
            )

            if status != _REQUEST_STATUS_PENDING_APPROVAL:
                return jsonify(
                    {"detail": f"Job is not pending approval (status={status})"}
                ), 409

            if not _can_actor_approve(actor, approval_required):
                return jsonify(
                    {"detail": "Forbidden: insufficient approval rights"}
                ), 403

            rejected_job_ids = [job_id]
            if request_type == _REQUEST_TYPE_BATCH and batch_id is not None:
                rejected_job_ids = _pending_batch_request_job_ids(
                    cursor, batch_id, _REQUEST_TYPE_BATCH
                )
                if not rejected_job_ids:
                    rejected_job_ids = [job_id]

            for rejected_job_id in rejected_job_ids:
                cursor.execute(
                    """
                    UPDATE rollback_jobs
                    SET status=%s, approved_by=%s, approved_at=CURRENT_TIMESTAMP
                    WHERE id=%s
                    """,
                    ("canceled", actor, rejected_job_id),
                )
                cursor.execute(
                    """
                    UPDATE rollback_job_items
                    SET status=%s, error=%s
                    WHERE job_id=%s AND status=%s
                    """,
                    (
                        "canceled",
                        "Rejected by approver",
                        rejected_job_id,
                        _REQUEST_STATUS_PENDING_APPROVAL,
                    ),
                )

        conn.commit()

    return jsonify(
        {
            "job_id": job_id,
            "batch_id": batch_id,
            "rejected_job_ids": rejected_job_ids,
            "rejected_by": actor,
            "status": "canceled",
        }
    )


@app.route("/api/v1/rollback/jobs/<int:job_id>/force-dry-run", methods=["POST"])
def force_dry_run_rollback_request(job_id: int):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    status,
                    batch_id,
                    request_type,
                    requested_endpoint,
                    approval_required
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )
            row = cursor.fetchone()

            if not row:
                return jsonify({"detail": "Job not found"}), 404

            (
                _id,
                status,
                batch_id,
                request_type,
                requested_endpoint,
                approval_required,
            ) = row

            request_type = _normalize_request_type(request_type)
            requested_endpoint = _normalize_request_endpoint(requested_endpoint)
            approval_required = approval_required or _approval_requirement_for_request(
                request_type, requested_endpoint
            )

            if status != _REQUEST_STATUS_PENDING_APPROVAL:
                return jsonify(
                    {"detail": f"Job is not pending approval (status={status})"}
                ), 409

            if not _can_actor_approve(actor, approval_required):
                return jsonify(
                    {"detail": "Forbidden: insufficient approval rights"}
                ), 403

            updated_job_ids = [job_id]
            if request_type == _REQUEST_TYPE_BATCH and batch_id is not None:
                updated_job_ids = _pending_batch_request_job_ids(
                    cursor, batch_id, _REQUEST_TYPE_BATCH
                )
                if not updated_job_ids:
                    updated_job_ids = [job_id]

            for updated_job_id in updated_job_ids:
                cursor.execute(
                    "UPDATE rollback_jobs SET dry_run=1 WHERE id=%s",
                    (updated_job_id,),
                )
                if request_type == _REQUEST_TYPE_DIFF:
                    _update_diff_payload(updated_job_id, {"dry_run": True})

        conn.commit()

    return jsonify(
        {
            "job_id": job_id,
            "batch_id": batch_id,
            "updated_job_ids": updated_job_ids,
            "updated_by": actor,
            "dry_run": True,
            "status": _REQUEST_STATUS_PENDING_APPROVAL,
        }
    )


@app.route("/api/v1/rollback/jobs/<int:job_id>/run-live", methods=["POST"])
def run_dry_run_job_live(job_id: int):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    queue_status = "queued"

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    requested_by,
                    status,
                    dry_run,
                    request_type,
                    requested_endpoint,
                    approval_required
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )
            row = cursor.fetchone()

            if not row:
                return jsonify({"detail": "Job not found"}), 404

            (
                requested_by,
                status,
                dry_run,
                request_type,
                requested_endpoint,
                approval_required,
            ) = row

            request_type = _normalize_request_type(request_type)
            requested_endpoint = _normalize_request_endpoint(requested_endpoint)
            approval_required = approval_required or _approval_requirement_for_request(
                request_type, requested_endpoint
            )

            if status != "completed":
                return jsonify(
                    {"detail": f"Job is not completed (status={status})"}
                ), 409

            if not bool(dry_run):
                return jsonify(
                    {"detail": "Job is already configured for live execution"}
                ), 409

            if not _can_run_live(actor, requested_by, approval_required):
                return jsonify({"detail": "Forbidden"}), 403

            cursor.execute(
                "SELECT COUNT(*) FROM rollback_job_items WHERE job_id=%s",
                (job_id,),
            )
            item_count_row = cursor.fetchone()
            item_count = int(item_count_row[0]) if item_count_row else 0

            if item_count == 0 and request_type == _REQUEST_TYPE_DIFF:
                payload = _load_diff_payload(job_id)
                if not payload:
                    return jsonify(
                        {"detail": "Cannot re-run this request without saved payload"}
                    ), 400

                if not _request_payload_has_diff_anchor(payload):
                    return jsonify(
                        {
                            "detail": "Cannot run live from this request because it has no diff anchor"
                        }
                    ), 400

                cursor.execute(
                    "UPDATE rollback_jobs SET dry_run=0, status='resolving' WHERE id=%s",
                    (job_id,),
                )
                conn.commit()

                _update_diff_payload(job_id, {"dry_run": False, "run_live_by": actor})
                _set_diff_error(job_id, None)
                resolve_diff_rollback_job.delay(job_id)
                queue_status = "resolving"
            else:
                cursor.execute(
                    "UPDATE rollback_jobs SET dry_run=0, status='queued' WHERE id=%s",
                    (job_id,),
                )
                cursor.execute(
                    """
                    UPDATE rollback_job_items
                    SET status='queued', error=NULL
                    WHERE job_id=%s
                    """,
                    (job_id,),
                )
                conn.commit()
                process_rollback_job.delay(job_id)

    return jsonify(
        {
            "job_id": job_id,
            "status": queue_status,
            "dry_run": False,
            "requested_by": requested_by,
            "run_live_by": actor,
        }
    )


@app.route("/api/v1/rollback/jobs/<int:job_id>/retry", methods=["POST"])
def retry_job(job_id):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT requested_by, status, request_type FROM rollback_jobs WHERE id=%s",
                (job_id,),
            )

            job = cursor.fetchone()

            if not job:
                return jsonify({"detail": "Job not found"}), 404

            if job[0] != actor:
                if "retry_any" not in _user_permissions(actor):
                    return jsonify({"detail": "Forbidden"}), 403

            current_status = str(job[1] or "") if len(job) > 1 else ""
            request_type = (
                _normalize_request_type(job[2]) if len(job) > 2 else _REQUEST_TYPE_QUEUE
            )

            if current_status == _REQUEST_STATUS_PENDING_APPROVAL:
                return jsonify(
                    {
                        "detail": "This request is pending approval and cannot be retried yet"
                    }
                ), 409

            cursor.execute(
                "SELECT COUNT(*) FROM rollback_job_items WHERE job_id=%s",
                (job_id,),
            )
            item_count_row = cursor.fetchone()
            item_count = int(item_count_row[0]) if item_count_row else 0

            if item_count == 0:
                payload = _load_diff_payload(job_id)
                if not payload:
                    return jsonify(
                        {"detail": "Cannot retry this job without saved diff payload"}
                    ), 400

                if (
                    request_type == _REQUEST_TYPE_DIFF
                    and current_status == _REQUEST_STATUS_PENDING_APPROVAL
                ):
                    return jsonify(
                        {"detail": "Diff request is still pending approval"}
                    ), 409

                cursor.execute(
                    "UPDATE rollback_jobs SET status='resolving' WHERE id=%s",
                    (job_id,),
                )
                conn.commit()
                _set_diff_error(job_id, None)
                status_updater.update_wiki_status(
                    editing="Resolving diff",
                    current_job=f"Resolving diff for job {job_id}",
                )
                resolve_diff_rollback_job.delay(job_id)
                return jsonify({"job_id": job_id, "status": "resolving"})

            cursor.execute(
                "UPDATE rollback_jobs SET status='queued' WHERE id=%s",
                (job_id,),
            )

            cursor.execute(
                """
                UPDATE rollback_job_items
                SET status='queued', error=NULL
                WHERE job_id=%s
                """,
                (job_id,),
            )

        conn.commit()

    status_updater.update_wiki_status(
        editing="Actively editing",
        current_job=f"Retrying job {job_id}",
    )
    process_rollback_job.delay(job_id)

    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/api/v1/rollback/jobs/<int:job_id>", methods=["DELETE"])
def cancel_rollback_job(job_id):
    actor = _rollback_api_actor()

    if actor is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, requested_by, status
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )

            job = cursor.fetchone()

            if not job:
                return jsonify({"detail": "Job not found"}), 404

            if job[1] != actor:
                actor_perms = _user_permissions(actor)
                # Fast-path: actors with no cross-user cancel permission are always denied.
                if "cancel_any" not in actor_perms and not is_maintainer(actor):
                    return jsonify({"detail": "Forbidden"}), 403

                # Tier check: the required privilege depends on the job owner's level.
                # Hierarchy: bot admin > maintainer > admin (sysop) > regular user.
                job_owner = job[1]
                if is_bot_admin(job_owner):
                    # Bot-admin job: only another bot admin may cancel it.
                    if "cancel_maintainer_jobs" not in actor_perms:
                        return jsonify(
                            {
                                "detail": "Forbidden: canceling a bot-admin's job requires bot-admin rights"
                            }
                        ), 403
                elif is_maintainer(job_owner):
                    # Regular maintainer's job: any maintainer (or bot admin) may cancel it.
                    if not is_maintainer(actor):
                        return jsonify(
                            {
                                "detail": "Forbidden: canceling a maintainer's job requires maintainer rights"
                            }
                        ), 403
                elif is_admin_user(job_owner):
                    # Admin job: any maintainer (or bot admin) may cancel it.
                    if "cancel_admin_jobs" not in actor_perms:
                        return jsonify(
                            {
                                "detail": "Forbidden: canceling an admin's job requires maintainer rights"
                            }
                        ), 403
                # else: regular user's job; cancel_any is sufficient (already checked above).

            if job[2] in {"completed", "failed", "canceled"}:
                return jsonify({"job_id": job_id, "status": job[2]})

            cursor.execute(
                "UPDATE rollback_jobs SET status=%s WHERE id=%s",
                ("canceled", job_id),
            )

            cursor.execute(
                """
                UPDATE rollback_job_items
                SET status=%s, error=%s
                WHERE job_id=%s AND status IN (%s, %s, %s, %s, %s)
                """,
                (
                    "canceled",
                    "Canceled by requester",
                    job_id,
                    "queued",
                    "running",
                    "resolving",
                    "staging",
                    _REQUEST_STATUS_PENDING_APPROVAL,
                ),
            )

        conn.commit()

    status_updater.update_wiki_status(
        editing="Idle",
        last_job=f"Job {job_id} canceled by {actor}",
    )
    _set_diff_error(job_id, None)

    return jsonify({"job_id": job_id, "status": "canceled"})


@app.route("/api/v1/rollback/jobs/<int:job_id>")
def get_rollback_job(job_id):
    username = session.get("username")

    if username is None:
        return jsonify({"detail": "Not authenticated"}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    id,
                    requested_by,
                    status,
                    dry_run,
                    created_at,
                    request_type,
                    requested_endpoint,
                    approved_endpoint,
                    approval_required,
                    approved_by,
                    approved_at
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )

            job = cursor.fetchone()

            if not job:
                return jsonify({"detail": "Job not found"}), 404

            if job[1] != username and "read_all" not in _user_permissions(username):
                return jsonify({"detail": "Forbidden"}), 403

            cursor.execute(
                """
                SELECT id, file_title, target_user, summary, status, error
                FROM rollback_job_items
                WHERE job_id=%s
                ORDER BY id ASC
                """,
                (job_id,),
            )

            items = cursor.fetchall()

    if _maybe_mark_stale_resolving_job_failed(job[0], job[2], job[4]):
        if len(job) >= 11:
            job = (
                job[0],
                job[1],
                "failed",
                job[3],
                job[4],
                job[5],
                job[6],
                job[7],
                job[8],
                job[9],
                job[10],
            )
        else:
            job = (job[0], job[1], "failed", job[3], job[4])

    if request.args.get("format") == "log":
        lines = []

        for item in items:
            item_id, title, target_user, _summary, status, error = item
            line = f"item_id={item_id} status={status} title={title} user={target_user}"

            if error:
                line += f" error={error}"

            lines.append(line)

        body = "\n".join(lines) + ("\n" if lines else "")
        return Response(body, mimetype="text/plain")

    diff_payload = _load_diff_payload(job_id) or {}
    diff_error = r.get(_diff_error_key(job_id))
    if not isinstance(diff_error, str):
        diff_error = None

    return jsonify(
        {
            "id": job[0],
            "requested_by": job[1],
            "status": job[2],
            "dry_run": bool(job[3]),
            "created_at": str(job[4]),
            "request_type": job[5] if len(job) > 5 else None,
            "requested_endpoint": job[6] if len(job) > 6 else None,
            "approved_endpoint": job[7] if len(job) > 7 else None,
            "approval_required": job[8] if len(job) > 8 else None,
            "approved_by": job[9] if len(job) > 9 else None,
            "approved_at": (str(job[10]) if len(job) > 10 and job[10] else None),
            "total": len(items),
            "completed": len([x for x in items if x[4] == "completed"]),
            "failed": len([x for x in items if x[4] == "failed"]),
            "error": diff_error,
            "diff": diff_payload.get("diff"),
            "oldid": diff_payload.get("oldid"),
            "resolved_user": diff_payload.get("resolved_user"),
            "resolved_timestamp": diff_payload.get("resolved_timestamp"),
            "revision_query": diff_payload.get("revision_query"),
            "contribs_query": diff_payload.get("contribs_query"),
            "mw_debug": diff_payload.get("mw_debug", []),
            "items": [
                {
                    "id": x[0],
                    "title": x[1],
                    "user": x[2],
                    "summary": x[3],
                    "status": x[4],
                    "error": x[5],
                }
                for x in items
            ],
        }
    )


@app.route("/")
def index():
    return render_template(
        "index.html",
        username=session.get("username"),
        type="index",
    )


@app.route("/login")
def login():
    _ensure_secret_key()

    if request.args.get("referrer"):
        session["referrer"] = request.args.get("referrer")

    consumer_token = _user_consumer_token()

    if consumer_token is None:
        app.logger.error("Missing USER_OAUTH_CONSUMER_KEY/USER_OAUTH_CONSUMER_SECRET")
        return redirect(url_for("index"))

    try:
        redirect_loc, request_token = mwoauth.initiate(
            MWOAUTH_BASE_URL,
            consumer_token,
            callback=_oauth_callback_url(),
        )
    except Exception:
        app.logger.exception("mwoauth.initiate failed")
        return redirect(url_for("index"))

    try:
        session["request_token"] = _serialize_request_token(request_token)
    except Exception:
        app.logger.exception("Unable to serialize OAuth request token")
        return redirect(url_for("index"))

    return redirect(redirect_loc)


@app.route("/mas-oauth-callback")
@app.route("/oauth-callback")
@app.route("/mwoauth-callback")
@app.route("/buckbot-oauth-callback")
def oauth_callback():
    _ensure_secret_key()

    if "request_token" not in session:
        return redirect(url_for("index"))

    consumer_token = _user_consumer_token()

    if consumer_token is None:
        app.logger.error("Missing USER_OAUTH_CONSUMER_KEY/USER_OAUTH_CONSUMER_SECRET")
        return redirect(url_for("index"))

    authenticated = False

    try:
        access_token = mwoauth.complete(
            MWOAUTH_INDEX_URL,
            consumer_token,
            _deserialize_request_token(session["request_token"]),
            request.query_string,
        )
        identity = mwoauth.identify(
            MWOAUTH_INDEX_URL,
            consumer_token,
            access_token,
        )
    except Exception:
        app.logger.exception("OAuth authentication failed")
    else:
        username = identity["username"]

        if not is_authorized(username):
            session.clear()
            return UNAUTHORIZED_MESSAGE, 403

        session["access_token"] = dict(zip(access_token._fields, access_token))
        session["username"] = username
        session["authorized"] = True
        session["is_maintainer"] = bool(is_maintainer(username))
        session["is_admin"] = "sysop" in get_user_groups(username)
        authenticated = True

    referrer = session.get("referrer")
    session["referrer"] = None

    if authenticated:
        return redirect(referrer or "/")

    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/api/v1/modules", methods=["GET"])
def module_registry_api():
    username = session.get("username")
    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    is_admin = bool(is_maintainer(username) or is_admin_user(username))
    modules = []
    for record in list_module_definitions():
        definition = record.definition
        modules.append(
            {
                "name": definition.name,
                "title": definition.title or definition.name,
                "enabled": bool(record.enabled),
                "ui_enabled": bool(definition.ui_enabled),
                "cron_jobs": [job.as_dict() for job in definition.cron_jobs],
                "has_access": bool(record.enabled or is_admin),
                "redis_namespace": definition.redis_namespace,
                "oauth_consumer_mode": definition.oauth_consumer_mode,
            }
        )

    return jsonify({"modules": modules})


@app.route("/api/v1/modules/<path:module_name>", methods=["GET"])
def module_registry_item_api(module_name: str):
    username = session.get("username")
    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    record = get_module_definition(module_name)
    if record is None:
        return jsonify({"detail": "Module not found"}), 404

    is_admin = bool(is_maintainer(username) or is_admin_user(username))
    if not user_has_module_access(module_name, username, is_maintainer=is_admin):
        return jsonify({"detail": "Forbidden"}), 403

    payload = record.as_dict()
    payload["has_access"] = True
    return jsonify(payload)


@app.route("/api/v1/modules/<path:module_name>/enabled", methods=["PUT"])
def module_registry_toggle_api(module_name: str):
    username = session.get("username")
    if not username:
        return jsonify({"detail": "Not authenticated"}), 401
    if not (is_maintainer(username) or is_admin_user(username)):
        return jsonify({"detail": "Forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    enabled = _parse_bool(payload.get("enabled"), default=True)
    record = get_module_definition(module_name)
    if record is None:
        return jsonify({"detail": "Module not found"}), 404

    set_module_enabled(module_name, enabled)
    return jsonify({"module": module_name, "enabled": bool(enabled)})


@app.route("/api/v1/modules/<path:module_name>/access", methods=["PUT"])
def module_registry_access_api(module_name: str):
    username = session.get("username")
    if not username:
        return jsonify({"detail": "Not authenticated"}), 401
    if not (is_maintainer(username) or is_admin_user(username)):
        return jsonify({"detail": "Forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    target_username = str(payload.get("username") or "").strip()
    enabled = _parse_bool(payload.get("enabled"), default=True)

    if not target_username:
        return jsonify({"detail": "Missing required parameter: username"}), 400

    record = get_module_definition(module_name)
    if record is None:
        return jsonify({"detail": "Module not found"}), 404

    upsert_module_access(module_name, target_username, enabled=enabled)
    return jsonify(
        {
            "module": module_name,
            "username": target_username,
            "enabled": bool(enabled),
        }
    )


@app.route("/api/v1/modules/install", methods=["POST"])
def module_registry_install_api():
    username = session.get("username")
    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    if not (is_maintainer(username) or is_admin_user(username)):
        return jsonify({"detail": "Forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    repo = str(payload.get("repo") or payload.get("url") or "").strip()
    enabled = _parse_bool(payload.get("enabled"), default=True)

    if not repo:
        return jsonify({"detail": "Missing required parameter: repo"}), 400

    try:
        definition = install_remote_module(repo, enabled_default=enabled)
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400
    except Exception:
        logging.exception("Failed to install remote module %s", repo)
        return jsonify({"detail": "Internal server error"}), 500

    return jsonify({"module": definition.name, "installed": True, "definition": definition.as_dict()})
