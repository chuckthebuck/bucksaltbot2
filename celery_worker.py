from app import celery

# expose the celery instance directly
app = celery

# Import task modules to register them with celery
import router  # noqa: E402,F401
import rollback_queue  # noqa: E402,F401
