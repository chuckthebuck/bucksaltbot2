#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"
load_local_env
ensure_venv
require_cmd npm

info "Canary: Python version"
run_python --version

info "Canary: checking installed framework dependencies"
run_python - <<'PY'
missing = []
for module_name in ("flask", "mwoauth", "requests", "pytest"):
    try:
        __import__(module_name)
    except ModuleNotFoundError:
        missing.append(module_name)

if missing:
    raise SystemExit(
        "Missing Python dependencies in .venv: "
        + ", ".join(missing)
        + "\nRun: bash scripts/install-framework.sh && bash scripts/install-modules.sh"
    )
PY

info "Canary: validating module pins and enabled module names"
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

print("Enabled:", ", ".join(sorted(enabled)) or "(none)")
print("Available:", ", ".join(sorted(available)) or "(none)")

if missing:
    raise SystemExit(
        "Missing enabled module package/manifest: " + ", ".join(missing)
    )
PY

info "Canary: generating frontend module registry"
npm run modules:frontend

info "Canary: production frontend build"
npm run build

info "Canary: focused framework/module tests"
ENABLE_MODULE_LOADING=0 run_python -m pytest \
	tests/test_module_registry.py \
	tests/test_module_runtime.py \
	tests/test_jobs_yaml_generator.py \
	-q

if [[ "${CANARY_FULL_TESTS:-0}" == "1" ]]; then
	info "Canary: full non-live pytest suite"
	ENABLE_MODULE_LOADING=0 run_python -m pytest tests -q --ignore=tests/live
else
	info "Skipping full test suite. Set CANARY_FULL_TESTS=1 to run tests minus tests/live."
fi

info "Local canary build passed"
