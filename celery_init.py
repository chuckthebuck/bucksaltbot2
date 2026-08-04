"""Bind Celery task execution to the framework Flask application context."""

from flask import Flask
from celery import Celery, Task


def celery_init_app(app: Flask) -> Celery:
    """Create, configure, and register the Celery instance for ``app``."""

    class FlaskTask(Task):
        """Run every task with Flask configuration and extensions available."""

        def __call__(self, *args, **kwargs):
            """Enter the application context before invoking task logic."""
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)

    celery_app.conf.update(app.config["CELERY"])

    celery_app.set_default()
    app.extensions["celery"] = celery_app

    return celery_app
