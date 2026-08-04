"""Store best-effort rollback progress projections in shared Redis."""

import os
import json
import redis

from redis_namespace import redis_namespace

REDIS_URL = os.environ.get(
    "TOOL_REDIS_URI", "redis://redis.svc.tools.eqiad1.wikimedia.cloud:6379"
)

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def job_key(job_id):
    """Return the deployment-namespaced progress key for one rollback job."""
    return f"{redis_namespace()}:rollback:job:{job_id}"


def set_progress(job_id, data, ttl=86400):
    """Replace one job's serialized progress snapshot with an expiry."""
    r.set(job_key(job_id), json.dumps(data), ex=ttl)


def get_progress(job_id):
    """Return one decoded progress snapshot, or ``None`` on cache miss."""
    val = r.get(job_key(job_id))
    if not val:
        return None
    return json.loads(val)


def update_progress(job_id, field):
    """Best-effort increment a named counter without affecting durable work."""
    key = job_key(job_id)
    try:
        val = r.get(key)
        if not val or not isinstance(val, (str, bytes, bytearray)):
            return

        data = json.loads(val)

        data[field] = data.get(field, 0) + 1

        r.set(key, json.dumps(data), ex=86400)
    except (TypeError, ValueError, redis.RedisError):
        # Progress updates are best-effort and should never crash job execution.
        return
