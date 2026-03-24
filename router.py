import os
import secrets
import time
from urllib.parse import parse_qs, urlparse

import mwoauth
import mwoauth.flask
import requests

from flask import (
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
    escape,
)

from app import MAX_JOB_ITEMS, flask_app as app, is_maintainer
from redis_state import get_progress, r
from rollback_queue import process_rollback_job
from toolsdb import get_conn

ALLOWED_GROUPS = {"sysop"}
GROUP_CACHE_TTL = 300
_group_cache = {}


def _extract_oldid(diff_value):
    if diff_value is None:
        raise ValueError("Missing diff parameter")

    raw = str(diff_value).strip()

    if not raw:
        raise ValueError("Missing diff parameter")

    if raw.isdigit():
        return int(raw)

    parsed = urlparse(raw)
    oldid = parse_qs(parsed.query).get("oldid", [None])[0]

    if oldid and str(oldid).strip().isdigit():
        return int(str(oldid).strip())

    raise ValueError("diff must be a revision id or URL containing oldid")


def fetch_diff_author_and_timestamp(oldid):
    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "prop": "revisions",
        "revids": str(oldid),
        "rvprop": "ids|user|timestamp",
        "format": "json",
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    pages = data.get("query", {}).get("pages", {})

    for page in pages.values():
        revisions = page.get("revisions") or []

        if revisions:
            revision = revisions[0]
            user = revision.get("user")
            timestamp = revision.get("timestamp")

            if user and timestamp:
                return {
                    "user": user,
                    "timestamp": timestamp,
                }

    raise ValueError("Revision not found for provided diff")


def fetch_contribs_after_timestamp(target_user, start_timestamp, limit=None):
    url = "https://commons.wikimedia.org/w/api.php"

    uccontinue = None
    results = []

    while True:
        remaining = None

        if limit is not None:
            remaining = max(limit - len(results), 0)

            if remaining == 0:
                break

        params = {
            "action": "query",
            "list": "usercontribs",
            "ucuser": target_user,
            "uclimit": str(min(500, remaining)) if remaining is not None else "500",
            "ucprop": "ids|title",
            "ucstart": start_timestamp,
            "ucdir": "newer",
            "format": "json",
        }

        if uccontinue:
            params["uccontinue"] = uccontinue

        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        contribs = data.get("query", {}).get("usercontribs", [])

        for edit in contribs:
            # Strictly after the diff timestamp.
            if edit.get("timestamp") and edit["timestamp"] > start_timestamp:
                results.append({
                    "title": edit["title"],
                    "user": target_user
                })

                if limit is not None and len(results) >= limit:
                    break

        if limit is not None and len(results) >= limit:
            break

        if not data.get("continue"):
            break

        uccontinue = data["continue"]["uccontinue"]

        time.sleep(0.1)

        if len(results) >= 10000:
            break

    return results


def create_rollback_jobs_from_diff(
    diff,
    summary,
    requested_by,
    dry_run=False,
    limit=None,
):
    oldid = _extract_oldid(diff)
    diff_metadata = fetch_diff_author_and_timestamp(oldid)

    target_user = diff_metadata["user"]
    start_timestamp = diff_metadata["timestamp"]

    items = fetch_contribs_after_timestamp(
        target_user,
        start_timestamp,
        limit=limit,
    )

    if not items:
        raise ValueError("No contributions found after the provided diff timestamp")

    batch_id = int(time.time() * 1000)
    job_ids = []

    with get_conn() as conn:
        with conn.cursor() as cursor:
            for i in range(0, len(items), MAX_JOB_ITEMS):
                chunk = items[i : i + MAX_JOB_ITEMS]

                cursor.execute(
                    """
                    INSERT INTO rollback_jobs
                    (requested_by, status, dry_run, batch_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (requested_by, "queued", 1 if dry_run else 0, batch_id),
                )

                job_id = cursor.lastrowid
                job_ids.append(job_id)

                for item in chunk:
                    cursor.execute(
                        """
                        INSERT INTO rollback_job_items
                        (job_id, file_title, target_user, summary, status)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            job_id,
                            item["title"],
                            item["user"],
                            summary or None,
                            "queued",
                        ),
                    )

        conn.commit()

    for job_id in job_ids:
        process_rollback_job.delay(job_id)

    return {
        "job_id": job_ids[0],
        "job_ids": job_ids,
        "chunks": len(job_ids),
        "batch_id": batch_id,
        "total_items": len(items),
        "status": "queued",
        "resolved_user": target_user,
        "resolved_timestamp": start_timestamp,
        "oldid": oldid,
    }
if not os.environ.get("NOTDEV"):
    from dotenv import load_dotenv

    load_dotenv()


def get_user_groups(username):
    now = time.time()

    cached = _group_cache.get(username)
    if cached and (now - cached["ts"] < GROUP_CACHE_TTL):
        return cached["groups"]

    url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "users",
        "ususers": username,
        "usprop": "groups",
        "format": "json",
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        users = data.get("query", {}).get("users", [])
        groups = users[0].get("groups", []) if users else []
    except Exception:
        app.logger.exception("Failed to fetch groups for %s", username)
        groups = []

    _group_cache[username] = {"groups": groups, "ts": now}
    return groups


def is_authorized(username):
    if not username:
        return False

    if is_maintainer(username):
        return True

    groups = get_user_groups(username)
    return any(group in ALLOWED_GROUPS for group in groups)


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
    configured = os.environ.get("USER_OAUTH_CALLBACK_URL")

    if configured:
        return configured

    tool_name = os.environ.get("TOOL_NAME") or "buckbot"

    return f"https://{tool_name}.toolforge.org/oauth-callback"


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


@app.route("/goto")
def goto():
    username = session.get("username")
    tab = request.args.get("tab")

    if not username:
        return redirect(url_for("login", referrer="/goto?tab=" + str(tab)))

    if tab == "rollback-queue":
        return redirect("/rollback-queue")

    if tab == "rollback-batch":
        if not is_maintainer(username):
            abort(403)
        return redirect("/rollback_batch")

    if tab == "rollback-all-jobs":
        if not is_maintainer(username):
            abort(403)
        return redirect("/rollback-queue/all-jobs")

    if tab == "rollback-from-diff":
        if not is_maintainer(username):
            abort(403)
        return redirect("/rollback-from-diff")

    if tab == "documentation":
        return redirect(
            "https://commons.wikimedia.org/wiki/User:Alachuckthebuck/unbuckbot"
        )

    return redirect("/rollback-queue")


@app.route("/api/v1/rollback/worker")
def worker_status():
    hb = r.get("rollback:worker:heartbeat")

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
<<<<<<< HEAD
def rollback_from_diff_api():
    username = session.get("username")

    if not username:
        return jsonify({"detail": "Not authenticated"}), 401

    if not is_maintainer(username):
        return jsonify({"detail": "Forbidden"}), 403

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

    try:
        result = create_rollback_jobs_from_diff(
            diff=diff,
            summary=summary,
            requested_by=username,
            dry_run=dry_run,
            limit=limit,
        )
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 400

    return jsonify(
        {
            **result,
            "diff": diff,
            "dry_run": dry_run,
            "limit": limit,
        }
    )


@app.route("/rollback-from-diff")
def rollback_from_diff_page():
    username = session.get("username")

    if not username:
        abort(401)

    if not is_maintainer(username):
        abort(403)

    return render_template(
        "rollback_from_diff.html",
        username=username,
        max_limit=10000,
        default_limit=100,
        type="rollback-from-diff",
    )

=======
def rollback_from_diff_page():
    user = request.args.get("user")
    diff = request.args.get("diff")
    summary = request.args.get("summary", "")
    dry_run = request.args.get("dry_run") == "1"

    # 🔒 Require login
    if "username" not in session:
        return redirect(url_for("login", next=request.url))

    username = session["username"]

    # Validate
    if not user or not diff:
        return "Missing parameters", 400

    # 👉 Call your existing backend logic
    result = create_rollback_jobs_from_diff(
        target_user=user,
        start_diff=int(diff),
        summary=summary,
        requested_by=username,
        dry_run=dry_run
    )

    return f"""
    <h2>Rollback job created</h2>
    <p>User: {escape(user)}</p>
    <p>Edits: {result['total_items']}</p>
    <p>Chunks: {result['chunks']}</p>
    <a href="/jobs">View progress</a>
    """

>>>>>>> 720a984b9a47dce3c5489377a4852e6d9bab7059
@app.route("/rollback-queue/all-jobs")
def rollback_queue_all_jobs_ui():
    username = session.get("username")

    if not username:
        abort(401)

    if not is_maintainer(username):
        abort(403)

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    j.id,
                    j.requested_by,
                    j.status,
                    j.dry_run,
                    j.created_at,
                    COUNT(i.id) AS total_items,
                    COALESCE(SUM(CASE WHEN i.status='completed' THEN 1 ELSE 0 END), 0) AS completed_items,
                    COALESCE(SUM(CASE WHEN i.status='failed' THEN 1 ELSE 0 END), 0) AS failed_items
                FROM rollback_jobs j
                LEFT JOIN rollback_job_items i ON i.job_id = j.id
                GROUP BY j.id, j.requested_by, j.status, j.dry_run, j.created_at
                ORDER BY j.id DESC
                """
            )

            jobs = cursor.fetchall()

    if request.args.get("format") == "json":
        return jsonify(
            {
                "jobs": [
                    {
                        "id": row[0],
                        "requested_by": row[1],
                        "status": row[2],
                        "dry_run": bool(row[3]),
                        "created_at": str(row[4]),
                        "total": int(row[5] or 0),
                        "completed": int(row[6] or 0),
                        "failed": int(row[7] or 0),
                    }
                    for row in jobs
                ]
            }
        )

    return render_template(
        "rollback_queue_all_jobs.html",
        jobs=jobs,
        username=username,
        type="rollback-all-jobs",
    )


@app.route("/rollback_batch")
def rollback_batch():
    username = session.get("username")

    if not username:
        abort(401)

    if not is_maintainer(username):
        abort(403)

    return render_template(
        "batch_rollback.html",
        username=username,
        type="batch-rollback",
    )


@app.route("/api/v1/rollback/jobs", methods=["GET"])
def list_rollback_jobs():
    username = session.get("username")
    if username is None:
        return jsonify({"detail": "Not authenticated"}), 401

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

    return jsonify(
        {
            "jobs": [
                {
                    "id": row[0],
                    "requested_by": row[1],
                    "status": row[2],
                    "dry_run": bool(row[3]),
                    "created_at": str(row[4]),
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

    payload = request.get_json(silent=True) or {}

    requested_by = payload.get("requested_by") or actor
    items = payload.get("items") or payload.get("files") or []
    dry_run = _parse_bool(payload.get("dry_run", False), default=False)

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

    job_ids = []

    with get_conn() as conn:
        with conn.cursor() as cursor:
            for i in range(0, len(items), MAX_JOB_ITEMS):
                chunk = items[i : i + MAX_JOB_ITEMS]

                cursor.execute(
                    """
                    INSERT INTO rollback_jobs
                    (requested_by, status, dry_run, batch_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (requested_by, "queued", 1 if dry_run else 0, batch_id),
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
                        (job_id, title, user, summary, "queued"),
                    )

        conn.commit()

    if not job_ids:
        return jsonify({"detail": "No valid items to process"}), 400

    for jid in job_ids:
        process_rollback_job.delay(jid)

    return jsonify(
        {
            "job_id": job_ids[0],
            "status": "queued",
            "batch_id": batch_id,
            "job_ids": job_ids,
            "chunks": len(job_ids),
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
                "SELECT requested_by FROM rollback_jobs WHERE id=%s",
                (job_id,),
            )

            job = cursor.fetchone()

            if not job:
                return jsonify({"detail": "Job not found"}), 404

            if job[0] != actor:
                return jsonify({"detail": "Forbidden"}), 403

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
                return jsonify({"detail": "Forbidden"}), 403

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
                WHERE job_id=%s AND status IN (%s, %s)
                """,
                ("canceled", "Canceled by requester", job_id, "queued", "running"),
            )

        conn.commit()

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
                SELECT id, requested_by, status, dry_run, created_at
                FROM rollback_jobs
                WHERE id=%s
                """,
                (job_id,),
            )

            job = cursor.fetchone()

            if not job:
                return jsonify({"detail": "Job not found"}), 404

            if job[1] != username and not is_maintainer(username):
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

    return jsonify(
        {
            "id": job[0],
            "requested_by": job[1],
            "status": job[2],
            "dry_run": bool(job[3]),
            "created_at": str(job[4]),
            "total": len(items),
            "completed": len([x for x in items if x[4] == "completed"]),
            "failed": len([x for x in items if x[4] == "failed"]),
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
            "https://meta.wikimedia.org",
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
            "https://meta.wikimedia.org/w/index.php",
            consumer_token,
            _deserialize_request_token(session["request_token"]),
            request.query_string,
        )
        identity = mwoauth.identify(
            "https://meta.wikimedia.org/w/index.php",
            consumer_token,
            access_token,
        )
    except Exception:
        app.logger.exception("OAuth authentication failed")
    else:
        username = identity["username"]

        if not is_authorized(username):
            session.clear()
            return "This tool is restricted to Commons admins and maintainers.", 403

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
