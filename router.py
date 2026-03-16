import os
import secrets

import mwoauth
import mwoauth.flask
from flask import jsonify, redirect, render_template, request, session, url_for
from app import flask_app as app
from rollback_queue import process_rollback_job
from toolsdb import get_conn
from redis_state import r, get_progress
import time


if not os.environ.get('NOTDEV'):
    from dotenv import load_dotenv
    load_dotenv()



def _ensure_secret_key():
    configured = app.config.get('SECRET_KEY') or os.environ.get('SECRET_KEY')
    if not configured:
        configured = os.environ.get('FALLBACK_SECRET_KEY', 'dev-insecure-secret-change-me')
    app.config['SECRET_KEY'] = configured
    return configured


_ensure_secret_key()


def _user_consumer_token():
    key = os.environ.get('USER_OAUTH_CONSUMER_KEY')
    secret = os.environ.get('USER_OAUTH_CONSUMER_SECRET')
    if not key or not secret:
        return None
    return mwoauth.ConsumerToken(key, secret)




def _serialize_request_token(request_token):
    if isinstance(request_token, dict):
        return request_token

    token_fields = getattr(request_token, '_fields', None)
    if token_fields:
        return dict(zip(token_fields, request_token))

    if isinstance(request_token, (tuple, list)) and len(request_token) == 2:
        return {'key': request_token[0], 'secret': request_token[1]}

    raise ValueError('Unsupported request token format')


def _deserialize_request_token(payload):
    if not isinstance(payload, dict):
        raise ValueError('request_token payload must be a dict')

    try:
        return mwoauth.RequestToken(**payload)
    except TypeError:
        key = payload.get('key')
        secret = payload.get('secret')
        if key and secret:
            return mwoauth.RequestToken(key, secret)
        raise

def _oauth_callback_url():
    configured = os.environ.get('USER_OAUTH_CALLBACK_URL')
    if configured:
        return configured

    tool_name = os.environ.get('TOOL_NAME') or 'buckbot'
    return f'https://{tool_name}.toolforge.org/mas-oauth-callback'


def _rollback_api_actor():
    username = session.get('username')
    if username:
        return username

    status_token = request.headers.get('X-Status-Token')
    expected_token = os.environ.get('STATUS_API_TOKEN')
    if status_token and expected_token and secrets.compare_digest(status_token, expected_token):
        return os.environ.get('STATUS_API_USER', 'status-site')

    return None


@app.route('/goto')
def goto():
    target = request.args.get('tab')
    if session.get('username') is None:
        return redirect(url_for('login', referrer='/goto?tab=' + str(target)))
    if target == 'rollback-queue':
        return redirect(url_for('rollback_queue_ui'))
    if target == 'documentation':
        return redirect('https://commons.wikimedia.org/wiki/User:Alachuckthebuck/unbuckbot')
    return redirect(url_for('rollback_queue_ui'))

@app.route("/api/v1/rollback/worker")
def worker_status():

    hb=r.get("rollback:worker:heartbeat")

    if not hb:
        return jsonify({"status":"offline"})

    age=time.time()-float(hb)

    return jsonify({
        "status":"online",
        "last_seen":age
    })

@app.route("/api/v1/rollback/jobs/progress")
def batch_job_progress():

    if session.get('username') is None:
        return jsonify({'detail':'Not authenticated'}),401

    ids=request.args.get("ids","")

    if not ids:
        return jsonify({"jobs":[]})

    job_ids=[int(x) for x in ids.split(",") if x.strip()]

    jobs=[]

    for jid in job_ids:

        p=get_progress(jid)

        if p:
            jobs.append({
                "id":jid,
                **p
            })

    return jsonify({"jobs":jobs})
@app.route('/rollback-queue')
def rollback_queue_ui():
    username = session.get('username')
    jobs = []

    if username:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    '''SELECT id, requested_by, status, dry_run, created_at
                       FROM rollback_jobs
                       WHERE requested_by=%s
                       ORDER BY id DESC
                       LIMIT 100''',
                    (username,),
                )
                jobs = cursor.fetchall()

    return render_template('rollback_queue.html', jobs=jobs, username=username, type='rollback-queue')


@app.route('/api/v1/rollback/jobs', methods=['POST'])
def create_rollback_job():
    actor = _rollback_api_actor()
    if actor is None:
        return jsonify({'detail': 'Not authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    requested_by = payload.get('requested_by') or actor
    items = payload.get('items') or payload.get('files') or []
    dry_run = bool(payload.get('dry_run', False))

    if requested_by != actor:
        return jsonify({'detail': 'requested_by must match authenticated user'}), 403
    if not isinstance(items, list) or len(items) == 0:
        return jsonify({'detail': 'items must be a non-empty list'}), 400

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                '''INSERT INTO rollback_jobs
                   (requested_by, status, dry_run)
                   VALUES (%s, %s, %s)''',
                (requested_by, 'queued', 1 if dry_run else 0),
            )
            job_id = cursor.lastrowid
            for item in items:
                title = (item.get('title') or item.get('file') or '').strip()
                user = (item.get('user') or '').strip()
                summary = item.get('summary')
                if not title or not user:
                    continue
                cursor.execute(
                    '''INSERT INTO rollback_job_items
                       (job_id, file_title, target_user, summary, status)
                       VALUES (%s, %s, %s, %s, %s)''',
                    (job_id, title, user, summary, 'queued'),
                )
        conn.commit()

    process_rollback_job.delay(job_id)
    return jsonify({'job_id': job_id, 'status': 'queued'})

@app.route('/api/v1/rollback/jobs/<int:job_id>/retry', methods=['POST'])
def retry_job(job_id):
    actor = _rollback_api_actor()
    if actor is None:
        return jsonify({'detail': 'Not authenticated'}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT requested_by FROM rollback_jobs WHERE id=%s",
                (job_id,),
            )
            job = cursor.fetchone()
            if not job:
                return jsonify({'detail': 'Job not found'}), 404

            if job[0] != actor:
                return jsonify({'detail': 'Forbidden'}), 403

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



@app.route('/api/v1/rollback/jobs/<int:job_id>', methods=['DELETE'])
def cancel_rollback_job(job_id):
    actor = _rollback_api_actor()
    if actor is None:
        return jsonify({'detail': 'Not authenticated'}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT id, requested_by, status FROM rollback_jobs WHERE id=%s',
                (job_id,),
            )
            job = cursor.fetchone()
            if not job:
                return jsonify({'detail': 'Job not found'}), 404
            if job[1] != actor:
                return jsonify({'detail': 'Forbidden'}), 403

            if job[2] in {'completed', 'failed', 'canceled'}:
                return jsonify({'job_id': job_id, 'status': job[2]})

            cursor.execute(
                'UPDATE rollback_jobs SET status=%s WHERE id=%s',
                ('canceled', job_id),
            )
            cursor.execute(
                '''UPDATE rollback_job_items
                   SET status=%s, error=%s
                   WHERE job_id=%s AND status IN (%s, %s)''',
                ('canceled', 'Canceled by requester', job_id, 'queued', 'running'),
            )
        conn.commit()

    return jsonify({'job_id': job_id, 'status': 'canceled'})


@app.route('/api/v1/rollback/jobs/<int:job_id>')
def get_rollback_job(job_id):
    if session.get('username') is None:
        return jsonify({'detail': 'Not authenticated'}), 401

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                '''SELECT id, requested_by, status, dry_run, created_at
                   FROM rollback_jobs WHERE id=%s''',
                (job_id,),
            )
            job = cursor.fetchone()
            if not job:
                return jsonify({'detail': 'Job not found'}), 404
            if job[1] != session['username']:
                return jsonify({'detail': 'Forbidden'}), 403
            cursor.execute(
                '''SELECT id, file_title, target_user, summary, status, error
                   FROM rollback_job_items WHERE job_id=%s ORDER BY id ASC''',
                (job_id,),
            )
            items = cursor.fetchall()

    return jsonify({
        'id': job[0],
        'requested_by': job[1],
        'status': job[2],
        'dry_run': bool(job[3]),
        'created_at': str(job[4]),
        'total': len(items),
        'completed': len([x for x in items if x[4] == 'completed']),
        'failed': len([x for x in items if x[4] == 'failed']),
        'items': [
            {
                'id': x[0],
                'title': x[1],
                'user': x[2],
                'summary': x[3],
                'status': x[4],
                'error': x[5],
            }
            for x in items
        ],
    })


@app.route('/api/v1/rollback/jobs', methods=['GET'])
def list_rollback_jobs():
    if session.get('username') is None:
        return jsonify({'detail': 'Not authenticated'}), 401
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                '''SELECT id, requested_by, status, dry_run, created_at
                   FROM rollback_jobs
                   WHERE requested_by=%s
                   ORDER BY id DESC
                   LIMIT 100''',
                (session['username'],),
            )
            jobs = cursor.fetchall()
    return jsonify({'jobs': [
        {
            'id': row[0],
            'requested_by': row[1],
            'status': row[2],
            'dry_run': bool(row[3]),
            'created_at': str(row[4]),
        }
        for row in jobs
    ]})

@app.route("/admin/jobs")
def admin_jobs():
    username = session.get("username")

    if not is_maintainer(username):
        abort(403)

    jobs = get_all_jobs()

    return render_template(
        "admin_jobs.html",
        jobs=jobs
    )
@app.route('/')
def index():
    return render_template('index.html', username=session.get('username'), type='index')


@app.route('/login')
def login():
    _ensure_secret_key()

    if request.args.get('referrer'):
        session['referrer'] = request.args.get('referrer')

    consumer_token = _user_consumer_token()
    app.logger.error("KEY: %s", os.environ.get("USER_OAUTH_CONSUMER_KEY"))

    if consumer_token is None:
        app.logger.error('Missing USER_OAUTH_CONSUMER_KEY/USER_OAUTH_CONSUMER_SECRET')
        return redirect(url_for('index'))

    try:
        redirect_loc, request_token = mwoauth.initiate(
            "https://meta.wikimedia.org",
            consumer_token,
            callback=_oauth_callback_url(),
        )
    except Exception:
        app.logger.exception('mwoauth.initiate failed')
        return redirect(url_for('index'))

    try:
        session['request_token'] = _serialize_request_token(request_token)
    except Exception:
        app.logger.exception('Unable to serialize OAuth request token')
        return redirect(url_for('index'))

    return redirect(redirect_loc)

@app.route('/mas-oauth-callback')
@app.route('/oauth-callback')
@app.route('/mwoauth-callback')
@app.route('/buckbot-oauth-callback')
def oauth_callback():
    _ensure_secret_key()
    if 'request_token' not in session:
        return redirect(url_for('index'))

    consumer_token = _user_consumer_token()
    if consumer_token is None:
        app.logger.error('Missing USER_OAUTH_CONSUMER_KEY/USER_OAUTH_CONSUMER_SECRET')
        return redirect(url_for('index'))

    authenticated = False

    try:
        access_token = mwoauth.complete(
            'https://meta.wikimedia.org/w/index.php',
            consumer_token,
            _deserialize_request_token(session['request_token']),
            request.query_string,
        )
        identity = mwoauth.identify(
            'https://meta.wikimedia.org/w/index.php',
            consumer_token,
            access_token,
        )
    except Exception:
        app.logger.exception('OAuth authentication failed')
    else:
        session['access_token'] = dict(zip(access_token._fields, access_token))
        session['username'] = identity['username']
        authenticated = True

    referrer = session.get('referrer')
    session['referrer'] = None
    if authenticated:
        return redirect(referrer or '/')
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)
