#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"
prepare_canary
require_cmd npm
ensure_local_services

export CHUCKBOT_LOCAL_SAFE_MODE="${CHUCKBOT_LOCAL_SAFE_MODE:-1}"
export ENABLE_MODULE_LOADING="${ENABLE_MODULE_LOADING:-1}"
export FLASK_DEBUG="${FLASK_DEBUG:-1}"
export PORT="${PORT:-5000}"
export VITE_ORIGIN="${VITE_ORIGIN:-http://localhost:5173}"
export LIVE_TEST_DISABLE_STATUS_UPDATES="${LIVE_TEST_DISABLE_STATUS_UPDATES:-1}"

if [[ "$CHUCKBOT_LOCAL_SAFE_MODE" != "1" ]]; then
	die "Refusing to run full local stack unless CHUCKBOT_LOCAL_SAFE_MODE=1"
fi

pids=()
cleanup() {
	for pid in "${pids[@]:-}"; do
		if kill -0 "$pid" >/dev/null 2>&1; then
			kill "$pid" >/dev/null 2>&1 || true
		fi
	done
}
trap cleanup EXIT INT TERM

info "Starting Vite dev asset server"
npm run dev &
pids+=("$!")

info "Starting Celery rollback worker in local safe mode"
C_FORCE_ROOT=true run_python -m celery -A celery_worker:app worker \
	--loglevel=INFO \
	--concurrency=1 \
	--max-tasks-per-child=20 &
pids+=("$!")

info "Starting module job controller"
run_python -m module_job_controller &
pids+=("$!")

info "Starting Flask/Gunicorn webservice"
info "Open http://127.0.0.1:$PORT"
run_python -m gunicorn -w 1 -b "127.0.0.1:$PORT" app:flask_app \
	--timeout 600 \
	--access-logfile - \
	--reload &
pids+=("$!")

wait
