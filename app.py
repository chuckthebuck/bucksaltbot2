import os
from flask import Flask
from celery import Celery
from blueprint import assets_blueprint
import requests
from functools import lru_cache

TOOLHUB_API = "https://toolhub.wikimedia.org/api/tools/buckbot/"

@lru_cache(maxsize=1)
def get_toolhub_maintainers():
    try:
        r = requests.get(TOOLHUB_API, timeout=5)
        r.raise_for_status()
        data = r.json()

        return {m["username"] for m in data.get("maintainers", [])}

    except Exception as e:
        print("Failed to load Toolhub maintainers:", e)
        return set()
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
import router
