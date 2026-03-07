#!/usr/bin/env bash
set -e

cat user-config.tmpl > user-config.py

celery -A app:celery worker \
  --loglevel=INFO \
  --concurrency=2 \
  -n buckbot-worker@%h
