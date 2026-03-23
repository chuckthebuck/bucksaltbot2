import os
import time
import threading
import requests

from flask_cors import CORS
from flask import Flask, session
from celery import Celery

from blueprint import assets_blueprint


BOT_ADMIN_ACCOUNTS = {
    u.strip().lower()
    for u in os.getenv("BOT_ADMIN_ACCOUNTS", "").split(",")
    if u.strip()
}

TOOLHUB_API = "https://toolhub.wikimedia.org/api/tools/buckbot/"

MAX_JOB_ITEMS = int(os.getenv("MAX_JOB_ITEMS", "50"))

_TOOLHUB_CACHE_TTL = 300  # 5 minutes
_toolhub_maintainers_cache = None
_toolhub_cache_expiry = 0.0
_toolhub_cache_lock = threading.Lock()


def get_toolhub_maintainers():
    global _toolhub_maintainers_cache, _toolhub_cache_expiry

    with _toolhub_cache_lock:
        if (
            _toolhub_maintainers_cache is not None
            and time.time() < _toolhub_cache_expiry
        ):
            return _toolhub_maintainers_cache

        try:
            r = requests.get(TOOLHUB_API, timeout=5)
            r.raise_for_status()
            data = r.json()

            result = {m["username"].lower() for m in data.get("maintainers", [])}

            _toolhub_maintainers_cache = result
            _toolhub_cache_expiry = time.time() + _TOOLHUB_CACHE_TTL
            return result

        except Exception as e:
            print("Failed to load Toolhub maintainers:", e)
            # Return stale cache if available rather than an empty set
            if _toolhub_maintainers_cache is not None:
                return _toolhub_maintainers_cache
            return set()


def is_maintainer(username):

    if not username:
        return False

    username = username.lower()

    # Hardcoded overrides
    if username in BOT_ADMIN_ACCOUNTS:
        return True

    maintainers = get_toolhub_maintainers()

    return username in maintainers


flask_app = Flask(__name__)
flask_app.config.update(
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=True
)
flask_app.register_blueprint(assets_blueprint)


flask_app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-insecure-secret")


CELERY_BROKER_URL = os.getenv(
    "CELERY_BROKER_URL", "redis://redis.svc.tools.eqiad1.wikimedia.cloud:6379/9"
)

CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)


celery = Celery(
    flask_app.import_name, broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


class ContextTask(celery.Task):
    def __call__(self, *args, **kwargs):
        with flask_app.app_context():
            return self.run(*args, **kwargs)


celery.Task = ContextTask


@flask_app.context_processor
def inject_user_permissions():

    username = session.get("username")

    return {"username": username, "is_maintainer": is_maintainer(username)}


import router  # noqa: E402,F401
CORS(flask_app, resources={
    r"/api/*": {
        "origins": ["https://commons.wikimedia.org"],
        "supports_credentials": True
    }
})