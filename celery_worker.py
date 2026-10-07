"""Expose the Celery application and import every framework task module."""

from app import celery

# Gunicorn/Celery entry points expect an ``app`` module attribute.
app = celery

# Decorated tasks register at import time, so workers must import each owner even
# if the web process has not exercised the corresponding route.
import router  # noqa: E402,F401
import rollback_queue  # noqa: E402,F401
import module_tasks  # noqa: E402,F401

# Optional vendored modules may own tasks while still sharing the framework's
# Celery broker and worker pool. Missing disabled packages must not stop the
# core rollback worker from starting.
try:
    import self_delete.queue  # noqa: E402,F401
except ModuleNotFoundError as exc:
    if exc.name not in {"self_delete", "self_delete.queue"}:
        raise
