import os
import redis

redis_url = 'redis://localhost:6379/9'

if 'DOCKER' in os.environ:
    redis_url = 'redis://redis:6379/0'

if 'NOTDEV' in os.environ:
    redis_url = 'redis://redis.svc.tools.eqiad1.wikimedia.cloud:6379/0'

rediscl = redis.Redis(host='localhost', port=6379, db=9)


if 'NOTDEV' in os.environ:
    rediscl = redis.Redis(
        host='redis.svc.tools.eqiad1.wikimedia.cloud',
        port=6379,
        db=0)
    
if 'DOCKER' in os.environ:
    rediscl = redis.Redis(
        host='redis',
        port=6379,
        db=0)

REDIS_KEY_PREFIX = 'mw-toolforge-match-and-split-'