#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"
require_cmd docker

if docker compose version >/dev/null 2>&1; then
	docker compose down
elif command -v docker-compose >/dev/null 2>&1; then
	docker-compose down
else
	die "Missing docker compose or docker-compose"
fi
