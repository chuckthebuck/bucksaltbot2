import os
import redis

if os.getenv("TOOLFORGE"):
    redis_url = "redis://redis.svc.tools.eqiad1.wikimedia.cloud:6379/0"
elif os.getenv("DOCKER"):
    redis_url = "redis://redis:6379/0"
else:
    redis_url = "redis://localhost:6379/9"

rediscl = redis.from_url(redis_url)

REDIS_KEY_PREFIX = "mw-toolforge-buckbot"
