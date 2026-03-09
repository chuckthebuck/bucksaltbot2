#!/usr/bin/env bash
set -e

export C_FORCE_ROOT=true
export CELERY_BROKER_URL="redis://redis.svc.tools.eqiad1.wikimedia.cloud:6379/9"
export CELERY_RESULT_BACKEND="redis://redis.svc.tools.eqiad1.wikimedia.cloud:6379/9"

rm -f user-config.py
cp user-config.tmpl user-config.py
chmod 600 user-config.py

echo "Starting Celery worker..."

celery -A celery_worker:app worker \
  --loglevel=INFO \
  --concurrency=2 \
  -Q $REDIS_KEY_PREFIX-celery-queue \
  -n buckbot-worker@%h
