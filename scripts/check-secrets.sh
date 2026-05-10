#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"
load_local_env

MODE="${1:-canary}"
status=0

check_required() {
	local name="$1"
	local value="${!name:-}"
	if [[ -z "$value" ]]; then
		printf 'missing  %s\n' "$name"
		status=1
	else
		printf 'present  %s\n' "$name"
	fi
}

check_optional() {
	local name="$1"
	local value="${!name:-}"
	if [[ -z "$value" ]]; then
		printf 'optional %s\n' "$name"
	else
		printf 'present  %s\n' "$name"
	fi
}

info "Checking $MODE environment without printing secret values"

case "$MODE" in
	canary)
		check_required SECRET_KEY
		check_optional USER_OAUTH_CONSUMER_KEY
		check_optional USER_OAUTH_CONSUMER_SECRET
		check_optional CONSUMER_TOKEN
		check_optional CONSUMER_SECRET
		check_optional ACCESS_TOKEN
		check_optional ACCESS_SECRET
		check_optional TOOL_TOOLSDB_PASSWORD
		;;
	live|toolforge)
		check_required SECRET_KEY
		check_required USER_OAUTH_CONSUMER_KEY
		check_required USER_OAUTH_CONSUMER_SECRET
		check_required CONSUMER_TOKEN
		check_required CONSUMER_SECRET
		check_required ACCESS_TOKEN
		check_required ACCESS_SECRET
		check_optional TOOL_TOOLSDB_PASSWORD
		;;
	*)
		printf 'Usage: %s [canary|live]\n' "$0" >&2
		exit 2
		;;
esac

check_optional BUCKBOT_HTTP_USER_AGENT
check_optional FOUR_AWARD_HTTP_USER_AGENT

exit "$status"
