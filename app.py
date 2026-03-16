import os
import requests

from flask import Flask, session
from celery import Celery
from cachetools import TTLCache

from blueprint import assets_blueprint


BOT_ADMIN_ACCOUNTS = {
    u.strip().lower()
    for u in os.getenv("BOT_ADMIN_ACCOUNTS", "").split(",")
    if u.strip()
}

TOOLHUB_API = "https://toolhub.wikimedia.org/api/tools/buckbot/"

MAX_JOB_ITEMS = int(os.getenv("MAX_JOB_ITEMS", "50"))

TOOLHUB_MAINTAINERS_CACHE_TTL = int(
    os.getenv("TOOLHUB_MAINTAINERS_CACHE_TTL", "300")
)

TOOLHUB_MAINTAINERS_CACHE = TTLCache(maxsize=1, ttl=TOOLHUB_MAINTAINERS_CACHE_TTL)


def get_toolhub_maintainers():
    # Return cached maintainers if available and not expired
    cached_maintainers = TOOLHUB_MAINTAINERS_CACHE.get("maintainers")
    if cached_maintainers is not None:
        return cached_maintainers

    try:
        r = requests.get(TOOLHUB_API, timeout=5)
        r.raise_for_status()
        data = r.json()

        maintainers = {
            m["username"].lower()
            for m in data.get("maintainers", [])
        }

        TOOLHUB_MAINTAINERS_CACHE["maintainers"] = maintainers
        return maintainers

    except Exception as e:
        print("Failed to load Toolhub maintainers:", e)
        # On failure, fall back to previously cached maintainers if any,
        # otherwise return an empty set (preserving existing behavior).
        if cached_maintainers is not None:
            return cached_maintainers
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

flask_app.register_blueprint(assets_blueprint)


flask_app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "dev-insecure-secret"
)


CELERY_BROKER_URL = os.getenv(
    "CELERY_BROKER_URL",
    "redis://redis.svc.tools.eqiad1.wikimedia.cloud:6379/9"
)

CELERY_RESULT_BACKEND = os.getenv(
    "CELERY_RESULT_BACKEND",
    CELERY_BROKER_URL
)


celery = Celery(
    flask_app.import_name,
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND
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

    return {
        "username": username,
        "is_maintainer": is_maintainer(username)
    }


import router
