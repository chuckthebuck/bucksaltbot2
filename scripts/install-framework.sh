#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"
load_local_env
ensure_venv
require_cmd npm

BASE_REQUIREMENTS="$REPO_ROOT/.tmp-requirements-framework.txt"
trap 'rm -f "$BASE_REQUIREMENTS"' EXIT

info "Installing Python framework dependencies without module pins"
grep -vE '^[[:space:]]*-r[[:space:]]+requirements-modules\.txt[[:space:]]*$' \
	requirements.txt > "$BASE_REQUIREMENTS"
run_pip install --upgrade pip setuptools wheel
run_pip install -r "$BASE_REQUIREMENTS"

info "Installing Node framework dependencies"
npm install

info "Framework dependencies installed"
printf 'Python: %s\n' "$("$(venv_python)" --version 2>&1)"
printf 'Node:   %s\n' "$(node --version)"
printf 'npm:    %s\n' "$(npm --version)"
