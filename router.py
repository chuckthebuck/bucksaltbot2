import os

import mwoauth
import mwoauth.flask
from flask import jsonify, redirect, render_template, request, session, url_for

from app import flask_app as app
from rollback_queue import process_rollback_job
from toolsdb import get_conn

if not os.environ.get('NOTDEV'):
    from dotenv import load_dotenv
    load_dotenv()

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')


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


@app.route('/rollback-queue')
def rollback_queue_ui():
    if session.get('username') is None:
        return redirect(url_for('login', referrer='/rollback-queue'))
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
    return render_template('rollback_queue.html', jobs=jobs, username=session['username'], type='rollback-queue')


@app.route('/api/v1/rollback/jobs', methods=['POST'])
def create_rollback_job():
    if session.get('username') is None:
        return jsonify({'detail': 'Not authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    requested_by = payload.get('requested_by') or ''
    items = payload.get('items') or payload.get('files') or []
    dry_run = bool(payload.get('dry_run', False))

    if requested_by != session['username']:
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


@app.route('/')
def index():
    return render_template('index.html', username=session.get('username'), type='index')


@app.route('/login')
def login():
    if request.args.get('referrer'):
        session['referrer'] = request.args.get('referrer')

    consumer_token = mwoauth.ConsumerToken(
        os.environ.get('USER_OAUTH_CONSUMER_KEY'),
        os.environ.get('USER_OAUTH_CONSUMER_SECRET'),
    )
    try:
        redirect_loc, request_token = mwoauth.initiate(
            'https://meta.wikimedia.org/w/index.php',
            consumer_token,
        )
    except Exception:
        app.logger.exception('mwoauth.initiate failed')
        return redirect(url_for('index'))

    session['request_token'] = dict(zip(request_token._fields, request_token))
    return redirect(redirect_loc)


@app.route('/mas-oauth-callback')
def oauth_callback():
    if 'request_token' not in session:
        return redirect(url_for('index'))

    consumer_token = mwoauth.ConsumerToken(
        os.environ.get('USER_OAUTH_CONSUMER_KEY'),
        os.environ.get('USER_OAUTH_CONSUMER_SECRET'),
    )

    try:
        access_token = mwoauth.complete(
            'https://meta.wikimedia.org/w/index.php',
            consumer_token,
            mwoauth.RequestToken(**session['request_token']),
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

    referrer = session.get('referrer')
    session['referrer'] = None
    return redirect(referrer or '/')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)
