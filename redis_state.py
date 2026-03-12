import os
import json
import redis

REDIS_URL = os.environ.get(
    "TOOL_REDIS_URI",
    "redis://redis.svc.tools.eqiad1.wikimedia.cloud:6379"
)

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def job_key(job_id):
    return f"rollback:job:{job_id}"


def set_progress(job_id, data, ttl=86400):
    r.set(job_key(job_id), json.dumps(data), ex=ttl)


def get_progress(job_id):
    val = r.get(job_key(job_id))
    if not val:
        return None
    return json.loads(val)


def update_progress(job_id, field):
    key = job_key(job_id)

    val = r.get(key)
    if not val:
        return

    data = json.loads(val)
    data[field] = data.get(field, 0) + 1
    
    r.set(key, json.dumps(data), ex=86400)
