#!/usr/bin/env bash
# Refresh supported module snapshots from their configured upstream revisions.
set -euo pipefail

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
	echo "Not inside a git repository." >&2
	exit 1
fi

cd "$(git rev-parse --show-toplevel)"

require_cmd() {
	# Fail early when a required source-control/build command is unavailable.
	command -v "$1" >/dev/null 2>&1 || {
		echo "Missing required command: $1" >&2
		exit 1
	}
}

require_cmd git
require_cmd npm
require_cmd rsync

if [[ -n "$(git status --porcelain)" && "${ALLOW_DIRTY_MODULE_UPDATE:-0}" != "1" ]]; then
	echo "Working tree is not clean. Commit or stash changes before updating vendored modules." >&2
	exit 1
fi

update_module() {
	# Replace one vendored subtree, retaining only its standalone repository files.
	local name="$1"
	local prefix="$2"
	local remote="$3"
	local branch="$4"
	local tmpdir

	if [[ ! -d "$prefix" ]]; then
		echo "Missing vendored module prefix for $name: $prefix" >&2
		exit 1
	fi

	echo "Updating $name from $remote ($branch)"
	tmpdir="$(mktemp -d)"
	trap 'rm -rf "$tmpdir"' RETURN
	git clone --depth 1 --branch "$branch" "$remote" "$tmpdir/$name"
	rsync -a --delete --exclude .git "$tmpdir/$name/" "$prefix/"
	rm -rf "$tmpdir"
	trap - RETURN
}

update_module \
	"4Award" \
	"vendor/modules/four_award" \
	"${FOUR_AWARD_REMOTE:-https://github.com/chuckthebuck/module4awardhelper.git}" \
	"${FOUR_AWARD_BRANCH:-framework-dev}"

update_module \
	"Chuck File Changer" \
	"vendor/modules/chuck_file_changer" \
	"${CHUCK_FILE_CHANGER_REMOTE:-https://github.com/chuckthebuck/Chuckthefilechange.git}" \
	"${CHUCK_FILE_CHANGER_BRANCH:-main}"

update_module \
	"Chuck the Salt Shack" \
	"vendor/modules/chuck_salt_shack" \
	"${CHUCK_SALT_SHACK_REMOTE:-https://github.com/chuckthebuck/chuck-the-salt-shack.git}" \
	"${CHUCK_SALT_SHACK_BRANCH:-main}"

python3 scripts/update-module-requirements.py
npm install
npm run modules:frontend
