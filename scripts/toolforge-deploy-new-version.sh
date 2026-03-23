#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$HOME"
REPO_URL="https://github.com/chuckthebuck/bucksaltbot2"
BRANCH="main"
BUILDPACK_CHANNEL="${BUILDPACK_CHANNEL:-default}"

build_args=()

case "$BUILDPACK_CHANNEL" in
	default)
		;;
	latest)
		build_args+=("--use-latest-versions")
		;;
	deprecated)
		build_args+=("--use-deprecated-versions")
		;;
	*)
		echo "Invalid BUILDPACK_CHANNEL: $BUILDPACK_CHANNEL" >&2
		echo "Expected one of: default, latest, deprecated" >&2
		exit 2
		;;
esac

cd "$REPO_DIR"

echo "Updating checkout in $REPO_DIR..."
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "Starting Toolforge build..."
toolforge build start "$REPO_URL" --ref "$BRANCH" "${build_args[@]}"

echo "Restarting webservice..."
toolforge webservice restart

echo "Reloading jobs..."
toolforge jobs load jobs.yaml

echo "Current jobs:"
toolforge jobs list
