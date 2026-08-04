"""Expose the Celery application and import every framework task module."""

from app import celery

# Gunicorn/Celery entry points expect an ``app`` module attribute.
app = celery

# Decorated tasks register at import time, so workers must import each owner even
# if the web process has not exercised the corresponding route.
import router  # noqa: E402,F401
import rollback_queue  # noqa: E402,F401
import module_tasks  # noqa: E402,F401
