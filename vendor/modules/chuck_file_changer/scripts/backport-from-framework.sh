#!/usr/bin/env bash
set -euo pipefail

FRAMEWORK_REPO="${BUCKBOT_FRAMEWORK_REPO:-/Users/chuckthebuck/Documents/GitHub/bucksaltbot2/5}"
PREFIX="${CHUCK_FILE_CHANGER_FRAMEWORK_PREFIX:-vendor/modules/chuck_file_changer}"
DRY_RUN=0

if [[ "${1:-}" == "--dry-run" ]]; then
	DRY_RUN=1
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
	echo "Not inside the Chuck File Changer git repository." >&2
	exit 1
fi

TARGET_REPO="$(git rev-parse --show-toplevel)"
SOURCE_DIR="$FRAMEWORK_REPO/$PREFIX"

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || {
		echo "Missing required command: $1" >&2
		exit 1
	}
}

require_cmd git
require_cmd rsync

if [[ ! -d "$FRAMEWORK_REPO/.git" ]]; then
	echo "Framework repo was not found: $FRAMEWORK_REPO" >&2
	echo "Set BUCKBOT_FRAMEWORK_REPO=/path/to/framework if needed." >&2
	exit 1
fi

if [[ ! -d "$SOURCE_DIR" ]]; then
	echo "Framework module source was not found: $SOURCE_DIR" >&2
	exit 1
fi

if [[ -n "$(git status --porcelain)" && "${ALLOW_DIRTY_CHUCK_FILE_CHANGE_BACKPORT:-0}" != "1" ]]; then
	echo "Standalone Chuck File Changer repo has uncommitted changes." >&2
	echo "Set ALLOW_DIRTY_CHUCK_FILE_CHANGE_BACKPORT=1 to overwrite/update them intentionally." >&2
	exit 1
fi

RSYNC_ARGS=(
	-a
	--delete
	--exclude .git
	--exclude .github
	--exclude .DS_Store
	--exclude .pytest_cache
	--exclude __pycache__
	--exclude '*.pyc'
	--exclude node_modules
	--exclude package-lock.json
	--exclude pytest-cache-files-*
	--exclude scripts
)

if [[ "$DRY_RUN" == "1" ]]; then
	RSYNC_ARGS+=(--dry-run --itemize-changes)
fi

echo "Backporting Chuck File Changer"
echo "  from: $SOURCE_DIR/"
echo "  to:   $TARGET_REPO/"

rsync "${RSYNC_ARGS[@]}" "$SOURCE_DIR/" "$TARGET_REPO/"

if [[ "$DRY_RUN" == "1" ]]; then
	echo "Dry run only. Nothing changed."
else
	echo "Backport complete."
	echo "Review with: git status --short"
fi
