#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export C_FORCE_ROOT=true
export NOTDEV="${NOTDEV:-1}"
export ENABLE_MODULE_LOADING="${ENABLE_MODULE_LOADING:-1}"
REDIS_NAMESPACE="${BUCKBOT_REDIS_NAMESPACE:-buckbot}"
CELERY_QUEUE="${BUCKBOT_CELERY_QUEUE:-${REDIS_NAMESPACE}.celery}"
CELERY_WORKER_NAME="${BUCKBOT_CELERY_WORKER_NAME:-${REDIS_NAMESPACE}-celery}"

mkdir -p "${TOOL_DATA_DIR:-./data}/logs" "${PYWIKIBOT_DIR:-./data/pywikibot}"

if [[ -f user-config.tmpl ]]; then
  rm -f user-config.py
  cp user-config.tmpl user-config.py
  chmod 600 user-config.py
fi

exec python -m celery -A celery_worker:app worker \
  --loglevel=INFO \
  --queues "$CELERY_QUEUE" \
  --hostname "${CELERY_WORKER_NAME}@%h" \
  --concurrency=2 \
  --max-tasks-per-child=50
