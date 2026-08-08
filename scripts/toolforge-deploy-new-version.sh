#!/usr/bin/env bash
# Pull the selected framework revision, build it on Toolforge, and restart jobs.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME}"
# Must name the deploy repository, not this framework's original upstream.
# The Build Service clones this URL; changes in another clone are invisible.
REPO_URL="${REPO_URL:-$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null || true)}"
BRANCH="${BRANCH:-main}"
BUILDPACK_CHANNEL="${BUILDPACK_CHANNEL:-latest}"

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

if [[ -z "$REPO_URL" ]]; then
	echo "REPO_URL is required when the checkout has no origin remote." >&2
	exit 2
fi

echo "Updating checkout in $REPO_DIR..."
git fetch origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "Starting Toolforge build..."
toolforge build start "$REPO_URL" --ref "$BRANCH" "${build_args[@]}"

echo "Restarting webservice..."
toolforge webservice buildservice restart

echo "Reloading jobs..."
# `load` flushes/recreates jobs whose definitions differ. Calling `flush`
# first adds a second asynchronous delete operation and can race the reload.
toolforge jobs load jobs.yaml

echo "Current jobs:"
toolforge jobs list
