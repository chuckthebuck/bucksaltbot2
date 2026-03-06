#!/usr/bin/env bash
set -e

id

# Prepare Pywikibot config
cat user-config.tmpl > user-config.py
ls -lah user-config.py



celery -A celery_init:celery_app worker \
  --loglevel=INFO \
  --concurrency=4 \
  -n buckbot-worker@%h
