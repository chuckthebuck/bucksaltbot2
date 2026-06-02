#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"
prepare_canary

case "${1:-status}" in
	status)
		info "Canary environment"
		printf '  .env: %s\n' "$REPO_ROOT/.env"
		printf '  venv: %s\n' "$VENV_DIR"
		printf '  DB:   %s@%s/%s\n' "${TOOL_TOOLSDB_USER:-user}" "${TOOL_TOOLSDB_HOST:-127.0.0.1}" "${TOOL_TOOLSDB_DATABASE:-chuckbot_local}"
		printf '  Redis:%s\n' "${TOOL_REDIS_URI:-redis://localhost:6379/0}"
		if docker_daemon_ready; then
			info "Docker daemon is reachable"
		else
			info "Docker daemon is not reachable"
		fi
		print_local_service_status
		;;
	up|start|fix)
		ensure_local_services
		print_local_service_status
		;;
	*)
		die "Usage: bash scripts/canary-doctor.sh [status|up]"
		;;
esac
