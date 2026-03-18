#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$HOME"
REPO_URL="https://github.com/chuckthebuck/bucksaltbot2"
BRANCH="main"

cd "$REPO_DIR"

echo "Updating checkout in $REPO_DIR..."
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "Starting Toolforge build..."
toolforge build start "$REPO_URL" --ref "$BRANCH"

echo "Restarting webservice..."
toolforge webservice restart

echo "Reloading jobs..."
toolforge jobs load jobs.yaml

echo "Current jobs:"
toolforge jobs list
