#!/usr/bin/env bash
# run_live_tests.sh – run the live integration test suite on Toolforge
#
# Required environment variables (bot OAuth credentials):
#   CONSUMER_TOKEN, CONSUMER_SECRET, ACCESS_TOKEN, ACCESS_SECRET
#
# Optional environment variables:
#   LIVE_TEST_USER   – username injected into admin sessions (default: live-test-admin)
#   TOOL_REDIS_URI   – Redis URL (defaults to the Toolforge Redis endpoint)
#
# Usage:
#   bash scripts/run_live_tests.sh            # run all live tests
#   bash scripts/run_live_tests.sh -k wiki    # run only wiki-related tests
#   bash scripts/run_live_tests.sh -x         # stop on first failure
#
# The script exits with the pytest exit code so it can be used in CI pipelines.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$REPO_ROOT"

# Prefer Python 3.11 on Toolforge bastion; fall back to python3.
if command -v python3.11 >/dev/null 2>&1; then
	BASE_PYTHON_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
	BASE_PYTHON_BIN="python3"
else
	echo "Error: neither 'python3.11' nor 'python3' was found in PATH" >&2
	exit 127
fi

# Keep an isolated environment so bastion login-node Python can run tests
# without relying on system-wide packages.
VENV_DIR="${LIVE_TEST_VENV_DIR:-$REPO_ROOT/.venv-live-tests}"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
	echo "Creating virtualenv: $VENV_DIR"
	"$BASE_PYTHON_BIN" -m venv "$VENV_DIR"
fi

PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

# Install dependencies when pytest is missing (first run or rebuilt venv).
if ! "$PYTHON_BIN" -m pytest --version >/dev/null 2>&1; then
	echo "Installing Python dependencies into $VENV_DIR"
	"$PIP_BIN" install --upgrade pip setuptools wheel
	"$PIP_BIN" install -r requirements.txt
fi

echo "=== BuckSaltBot2 live integration tests ==="
echo "Working directory: $(pwd)"
echo "Base Python: $($BASE_PYTHON_BIN --version 2>&1)"
echo "Venv Python: $($PYTHON_BIN --version 2>&1)"
echo "Pytest: $($PYTHON_BIN -m pytest --version 2>&1)"
echo ""

$PYTHON_BIN -m pytest tests/live/ -v --tb=short "$@"
