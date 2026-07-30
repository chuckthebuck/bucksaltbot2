#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Import the application factory module so enabled module manifests and their
# API blueprints are registered before Gunicorn begins serving requests.
export NOTDEV="${NOTDEV:-1}"
export ENABLE_MODULE_LOADING="${ENABLE_MODULE_LOADING:-1}"

exec gunicorn -w 4 -b "0.0.0.0:${PORT:-8000}" app:flask_app \
  --timeout 600 \
  --access-logfile -
