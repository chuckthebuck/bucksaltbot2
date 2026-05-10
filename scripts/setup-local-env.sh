#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
	info "Creating .env from .env.example"
	cp .env.example .env
else
	info ".env already exists; leaving it unchanged"
fi

for key in TOOL_TOOLSDB_DATABASE CHUCKBOT_LOCAL_SAFE_MODE LIVE_TEST_DISABLE_STATUS_UPDATES; do
	if ! grep -qE "^${key}=" .env; then
		value="$(grep -E "^${key}=" .env.example | tail -1 || true)"
		if [[ -n "$value" ]]; then
			info "Adding missing $key to .env"
			printf '\n%s\n' "$value" >> .env
		fi
	fi
done

mkdir -p data/logs data/pywikibot

info "Local env files/directories are ready"
printf '\nNext:\n'
printf '  1. Edit .env if you need real OAuth, Redis, or database values.\n'
printf '  2. Run bash scripts/install-framework.sh\n'
printf '  3. Run bash scripts/install-modules.sh\n'
printf '  4. Run bash scripts/canary-build.sh\n'
