"""Compatibility Redis client configured like the rest of the framework."""

import os

import redis

from redis_namespace import redis_namespace


redis_url = os.getenv(
    "TOOL_REDIS_URI", "redis://redis.svc.tools.eqiad1.wikimedia.cloud:6379/0"
)
rediscl = redis.Redis.from_url(redis_url)

# Callers should prefix their keys with this value when using this legacy
# helper directly. New framework code uses router.framework_config instead.
REDIS_KEY_PREFIX = redis_namespace()
