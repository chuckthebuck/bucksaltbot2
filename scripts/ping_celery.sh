#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export NOTDEV="${NOTDEV:-1}"
export ENABLE_MODULE_LOADING="${ENABLE_MODULE_LOADING:-1}"

# Importing the configured app applies the same Redis broker namespace as the
# worker, so this broadcast cannot target another tool's Celery workers.
exec python -m celery -A celery_worker:app inspect ping --timeout=10
