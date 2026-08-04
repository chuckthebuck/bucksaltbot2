#!/usr/bin/env bash
# Start the local canary web process after preparing isolated backing services.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"
prepare_canary
ensure_local_services

export FLASK_DEBUG="${FLASK_DEBUG:-1}"
export ENABLE_MODULE_LOADING="${ENABLE_MODULE_LOADING:-1}"
export CHUCKBOT_LOCAL_SAFE_MODE="${CHUCKBOT_LOCAL_SAFE_MODE:-1}"
export LIVE_TEST_DISABLE_STATUS_UPDATES="${LIVE_TEST_DISABLE_STATUS_UPDATES:-1}"
export PORT="${PORT:-5000}"

info "Starting local framework web canary on http://127.0.0.1:$PORT"
info "Scoped safe mode is on for rollback/module-runner paths; File Changer apply is excluded."
info "When FLASK_DEBUG=1, run a separate Vite server on ${VITE_ORIGIN:-http://localhost:5173}."
info "This starts the web process only. Use scripts/run-local-full.sh for Celery and the module controller."
exec "$(venv_python)" -m gunicorn -w 1 -b "127.0.0.1:$PORT" app:flask_app \
	--timeout 600 \
	--access-logfile - \
	--reload
