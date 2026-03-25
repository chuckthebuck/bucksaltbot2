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

echo "=== BuckSaltBot2 live integration tests ==="
echo "Working directory: $(pwd)"
echo "Python: $(python --version 2>&1)"
echo ""

python -m pytest tests/live/ -v --tb=short "$@"
