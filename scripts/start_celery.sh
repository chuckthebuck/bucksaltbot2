#!/usr/bin/env bash
set -e

cat user-config.tmpl > user-config.py
chmod 600 user-config.py
chown $(id -u):$(id -g) user-config.py

celery -A app:celery worker \
  --loglevel=INFO \
  --concurrency=2 \
  -n buckbot-worker@%h
