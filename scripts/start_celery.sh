#!/usr/bin/env bash
set -e

id

# Prepare Pywikibot config
cat user-config.tmpl > user-config.py
ls -lah user-config.py

echo "Waiting for Redis..."

until nc -z redis 6379; do
  sleep 2
done

echo "Redis is ready"

celery -A celery_init:celery_app worker \
  --loglevel=INFO \
  --concurrency=4 \
  -n buckbot-worker@%h
