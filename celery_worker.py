from app import celery

# expose the celery instance directly
app = celery

# Import task modules to register them with celery
import router  # noqa: F401, E402
import rollback_queue  # noqa: F401, E402
