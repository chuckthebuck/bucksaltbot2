#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"
load_local_env
ensure_venv
require_cmd npm

if grep -qE '^[[:space:]]*[^#[:space:]]' requirements-modules.txt; then
	info "Installing pinned Python modules from requirements-modules.txt"
	run_pip install --no-build-isolation -r requirements-modules.txt
else
	info "requirements-modules.txt has no active module pins"
fi

info "Installing npm dependencies, including any pinned frontend module packages"
npm install

info "Generating static frontend module registry"
npm run modules:frontend

info "Validating enabled module manifests and installed entry points"
ENABLE_MODULE_LOADING=0 run_python - <<'PY'
from pathlib import Path
from router.module_registry import (
    discover_installed_module_definitions,
    discover_module_definitions,
    load_enabled_module_names,
)

enabled = load_enabled_module_names()
local = {definition.name: definition for definition in discover_module_definitions(Path("modules"))}
installed = {definition.name: definition for definition in discover_installed_module_definitions()}
available = set(local) | set(installed)
missing = sorted(enabled - available)

print("Enabled modules:", ", ".join(sorted(enabled)) or "(none)")
print("Local manifests:", ", ".join(sorted(local)) or "(none)")
print("Installed package manifests:", ", ".join(sorted(installed)) or "(none)")

if missing:
    raise SystemExit(
        "Enabled module(s) are not installed or locally bundled: " + ", ".join(missing)
    )
PY

info "Module dependencies installed and validated"
