#!/usr/bin/env bash
set -euo pipefail

# Import the application factory module so enabled module manifests and their
# API blueprints are registered before Gunicorn begins serving requests.
export NOTDEV="${NOTDEV:-1}"
export ENABLE_MODULE_LOADING="${ENABLE_MODULE_LOADING:-1}"

exec gunicorn -w 4 -b "0.0.0.0:${PORT}" app:flask_app \
  --timeout 600 \
  --access-logfile -
