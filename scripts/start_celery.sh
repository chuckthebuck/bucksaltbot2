#!/usr/bin/env bash
set -e

export C_FORCE_ROOT=true
export NOTDEV=1


rm -f user-config.py
cp user-config.tmpl user-config.py
chmod 600 user-config.py

python -m celery -A celery_worker:app worker \
  --loglevel=INFO \
  --concurrency=2 \
  --max-tasks-per-child=50
