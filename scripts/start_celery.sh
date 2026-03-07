#!/usr/bin/env bash
set -e
export C_FORCE_ROOT=true

rm -f user-config.py
cp user-config.tmpl user-config.py
chmod 600 user-config.py

echo "Starting Celery worker..."

celery -A app:celery worker \
  --loglevel=INFO \
  --concurrency=2 \
  -n buckbot-worker@%h
