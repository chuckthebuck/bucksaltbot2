#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="${BUCKBOT_VENV_DIR:-$REPO_ROOT/.venv}"

info() {
	printf '==> %s\n' "$*"
}

die() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 1
}

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

base_python() {
	if command -v python3.11 >/dev/null 2>&1; then
		printf 'python3.11\n'
	elif command -v python3 >/dev/null 2>&1; then
		printf 'python3\n'
	else
		die "Missing python3.11 or python3"
	fi
}

venv_python() {
	if [[ -x "$VENV_DIR/bin/python3.11" ]]; then
		printf '%s/bin/python3.11\n' "$VENV_DIR"
	elif [[ -x "$VENV_DIR/bin/python3" ]]; then
		printf '%s/bin/python3\n' "$VENV_DIR"
	elif [[ -x "$VENV_DIR/bin/python" ]]; then
		printf '%s/bin/python\n' "$VENV_DIR"
	else
		die "Virtualenv exists but no executable Python was found in $VENV_DIR/bin"
	fi
}

venv_pip() {
	printf '%s/bin/pip\n' "$VENV_DIR"
}

ensure_venv() {
	local python_bin
	python_bin="$(base_python)"
	if [[ ! -d "$VENV_DIR" ]]; then
		info "Creating Python virtualenv at $VENV_DIR"
		"$python_bin" -m venv "$VENV_DIR"
	fi
	venv_python >/dev/null
}

load_local_env() {
	local env_file="${1:-$REPO_ROOT/.env}"
	if [[ -f "$env_file" ]]; then
		info "Loading environment from $env_file"
		set -a
		# shellcheck disable=SC1090
		source "$env_file"
		set +a
	fi
}

apply_local_service_defaults() {
	export TOOL_REDIS_URI="${TOOL_REDIS_URI:-redis://localhost:6379/0}"
	export CELERY_BROKER_URL="${CELERY_BROKER_URL:-redis://localhost:6379/9}"
	export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-redis://localhost:6379/9}"
	export TOOL_TOOLSDB_HOST="${TOOL_TOOLSDB_HOST:-127.0.0.1}"
	export TOOL_TOOLSDB_USER="${TOOL_TOOLSDB_USER:-user}"
	export TOOL_TOOLSDB_PASSWORD="${TOOL_TOOLSDB_PASSWORD:-password}"
	export TOOL_TOOLSDB_DATABASE="${TOOL_TOOLSDB_DATABASE:-chuckbot_local}"
}

run_python() {
	"$(venv_python)" "$@"
}

run_pip() {
	"$(venv_pip)" "$@"
}

compose_cmd() {
	if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
		printf 'docker compose\n'
	elif command -v docker-compose >/dev/null 2>&1; then
		printf 'docker-compose\n'
	else
		return 1
	fi
}

wait_for_tcp() {
	local host="$1"
	local port="$2"
	local label="${3:-$host:$port}"
	local timeout_seconds="${4:-30}"
	run_python - "$host" "$port" "$label" "$timeout_seconds" <<'PY'
import socket
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])
label = sys.argv[3]
timeout_seconds = int(sys.argv[4])

deadline = time.time() + timeout_seconds
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=1):
            raise SystemExit(0)
    except OSError:
        time.sleep(0.5)
raise SystemExit(f"{label} did not become reachable on {host}:{port}")
PY
}

wait_for_mysql() {
	local host="${TOOL_TOOLSDB_HOST:-127.0.0.1}"
	local user="${TOOL_TOOLSDB_USER:-user}"
	local password="${TOOL_TOOLSDB_PASSWORD:-password}"
	local database="${TOOL_TOOLSDB_DATABASE:-chuckbot_local}"
	local timeout_seconds="${1:-90}"
	run_python - "$host" "$user" "$password" "$database" "$timeout_seconds" <<'PY'
import sys
import time

import pymysql

host, user, password, database, timeout_seconds = sys.argv[1:6]
timeout_seconds = int(timeout_seconds)

deadline = time.time() + timeout_seconds
last_error = None
while time.time() < deadline:
    try:
        conn = pymysql.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            connect_timeout=2,
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        conn.close()
        raise SystemExit(0)
    except Exception as exc:  # noqa: BLE001 - readiness probe reports final error
        last_error = exc
        time.sleep(1)

raise SystemExit(
    f"MariaDB did not become query-ready for {user}@{host}/{database}: {last_error}"
)
PY
}

wait_for_redis() {
	local redis_url="${TOOL_REDIS_URI:-redis://localhost:6379/0}"
	local timeout_seconds="${1:-30}"
	run_python - "$redis_url" "$timeout_seconds" <<'PY'
import sys
import time

import redis

redis_url = sys.argv[1]
timeout_seconds = int(sys.argv[2])

deadline = time.time() + timeout_seconds
last_error = None
while time.time() < deadline:
    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True)
        client.ping()
        raise SystemExit(0)
    except Exception as exc:  # noqa: BLE001 - readiness probe reports final error
        last_error = exc
        time.sleep(0.5)

raise SystemExit(f"Redis did not become ping-ready at {redis_url}: {last_error}")
PY
}

local_services_ready() {
	wait_for_redis 1 >/dev/null 2>&1 && wait_for_mysql 1 >/dev/null 2>&1
}

ensure_local_services() {
	local auto_start="${LOCAL_SERVICES_AUTO_START:-1}"
	if local_services_ready; then
		info "Local Redis and MariaDB are reachable"
		return 0
	fi

	if [[ "$auto_start" != "1" ]]; then
		die "Local Redis/MariaDB are not reachable. Run: bash scripts/local-services-up.sh"
	fi

	if ! compose_cmd >/dev/null 2>&1; then
		die "Local Redis/MariaDB are not reachable and Docker Compose is unavailable. Start MySQL/Redis yourself or install Docker Compose."
	fi

	info "Local Redis/MariaDB are not reachable; starting Docker Compose services"
	bash "$REPO_ROOT/scripts/local-services-up.sh"
}
