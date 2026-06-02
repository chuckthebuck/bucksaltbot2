#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"
prepare_local_env

info "Local env files/directories are ready"
printf '\nNext:\n'
printf '  1. Edit .env if you need real OAuth, Redis, or database values.\n'
printf '  2. Run bash scripts/install-framework.sh\n'
printf '  3. Run bash scripts/install-modules.sh\n'
printf '  4. Run bash scripts/canary-build.sh\n'
