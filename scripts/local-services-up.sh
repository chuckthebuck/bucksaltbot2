#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"
prepare_canary
ensure_docker_daemon

read -r -a COMPOSE <<<"$(compose_cmd)" || die "Missing docker compose or docker-compose"

info "Starting local Redis and MariaDB"
"${COMPOSE[@]}" up -d redis mariadb

info "Waiting for Redis to answer PING"
wait_for_redis 30

info "Waiting for MariaDB to accept queries"
wait_for_mysql 90

info "Local services are up"
