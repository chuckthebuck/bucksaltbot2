#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

cd "$REPO_ROOT"
load_local_env
ensure_venv
require_cmd npm

run_unit_tests() {
	# Local runtime safety/dev flags intentionally change application behavior.
	# Unit tests need framework defaults and provide their own external-service mocks.
	env \
		-u BOT_NAME \
		-u TOOL_NAME \
		-u CHUCKBOT_LOCAL_SAFE_MODE \
		-u FLASK_DEBUG \
		-u LIVE_TEST_DISABLE_STATUS_UPDATES \
		ENABLE_MODULE_LOADING=0 \
		"$(venv_python)" "$@"
}

info "Canary: Python version"
run_python --version

info "Canary: framework self-test without external services"
ENABLE_MODULE_LOADING=0 run_python -m framework_selftest

info "Canary: checking vendored module autoversioning"
python3 scripts/check-module-autoversioning.py

info "Canary: checking generated Salt Shack registry"
PYTHONPATH=vendor/modules/chuck_salt_shack/modules \
	run_python -m chuck_salt_shack.build --check

info "Canary: generating frontend module registry"
npm run modules:frontend

info "Canary: production frontend build"
npm run build

info "Canary: focused framework/module tests"
run_unit_tests -m pytest \
	tests/test_module_registry.py \
	tests/test_module_runtime.py \
	tests/test_jobs_yaml_generator.py \
	tests/test_chuck_salt_shack_module.py \
	tests/test_wiki_actions.py \
	-q

if [[ "${CANARY_FULL_TESTS:-0}" == "1" ]]; then
	info "Canary: full non-live pytest suite"
	run_unit_tests -m pytest tests -q --ignore=tests/live
else
	info "Skipping full test suite. Set CANARY_FULL_TESTS=1 to run tests minus tests/live."
fi

info "Local canary build passed"
