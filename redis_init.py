import redis

REDIS_HOST = "redis.svc.tools.eqiad1.wikimedia.cloud"
REDIS_PORT = 6379
REDIS_DB = 9

redis_url = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

rediscl = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB
)

REDIS_KEY_PREFIX = "mw-toolforge-buckbot"
