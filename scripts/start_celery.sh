#!/usr/bin/env bash
set -e

export C_FORCE_ROOT=true
export NOTDEV="${NOTDEV:-1}"

mkdir -p "${TOOL_DATA_DIR:-./data}/logs" "${PYWIKIBOT_DIR:-./data/pywikibot}"

if [[ -f user-config.tmpl ]]; then
  rm -f user-config.py
  cp user-config.tmpl user-config.py
  chmod 600 user-config.py
fi

python -m celery -A celery_worker:app worker \
  --loglevel=INFO \
  --concurrency=2 \
  --max-tasks-per-child=50
