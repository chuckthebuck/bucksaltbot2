#!/usr/bin/env bash
# Copy the committed Salt Shack snapshot into its standalone repository.
#
# A git subtree split is prohibitively slow here because it walks the complete
# Buckbot history for a small vendored snapshot. This helper instead clones the
# target branch, overlays only vendor/modules/chuck_salt_shack, and creates one
# ordinary Salt Shack commit. It never exposes framework files to the target.
set -euo pipefail

REMOTE="${CHUCK_SALT_SHACK_REMOTE:-https://github.com/chuckthebuck/chuck-the-salt-shack.git}"
BRANCH="${CHUCK_SALT_SHACK_BRANCH:-main}"
PREFIX="vendor/modules/chuck_salt_shack"
COMMIT_MESSAGE="${CHUCK_SALT_SHACK_BACKPORT_MESSAGE:-chore: sync vendored Salt Shack snapshot}"
DRY_RUN=0

usage() {
	cat <<'EOF'
Usage: bash scripts/backport-chuck-salt-shack-subtree.sh [--dry-run]

Copy the committed vendor/modules/chuck_salt_shack snapshot into the configured
Salt Shack repository and branch. The default remote and branch can be changed
with CHUCK_SALT_SHACK_REMOTE and CHUCK_SALT_SHACK_BRANCH.

--dry-run clones the target and prints the exact Salt Shack-only diff without
creating a commit or pushing. Always run it before the non-dry-run command.
EOF
}

case "${1:-}" in
"")
	;;
--dry-run)
	DRY_RUN=1
	;;
-h|--help)
	usage
	exit 0
	;;
*)
	echo "Unknown option: $1" >&2
	usage >&2
	exit 2
	;;
esac

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
	echo "Not inside a git repository." >&2
	exit 1
fi
if ! command -v rsync >/dev/null 2>&1; then
	echo "Missing required command: rsync" >&2
	exit 127
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if [[ ! -d "$PREFIX" ]]; then
	echo "Missing subtree prefix: $PREFIX" >&2
	exit 1
fi

if [[ -n "$(git status --porcelain -- "$PREFIX")" ]]; then
	echo "Refusing to backport uncommitted Salt Shack files." >&2
	echo "Commit the reviewed framework snapshot first so the backport is reproducible." >&2
	exit 1
fi

SOURCE_COMMIT="$(git rev-parse HEAD)"
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/chuck-salt-shack-backport.XXXXXX")"
cleanup() {
	rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

TARGET_DIR="$TEMP_DIR/repository"
echo "Cloning $REMOTE branch $BRANCH for a Salt Shack-only backport..."
git clone --quiet --depth 1 --branch "$BRANCH" "$REMOTE" "$TARGET_DIR"

# The source is the subtree's contents, not the framework checkout. Excluding
# .git protects the target clone's own repository metadata.
rsync -a --delete --exclude='.git' "$PREFIX/" "$TARGET_DIR/"

cd "$TARGET_DIR"
git add --all
if git diff --cached --quiet; then
	echo "Salt Shack already matches Buckbot snapshot $SOURCE_COMMIT. Nothing to backport."
	exit 0
fi

echo "Salt Shack changes from Buckbot snapshot $SOURCE_COMMIT:"
git diff --cached --stat
git diff --cached --check

if [[ "$DRY_RUN" == "1" ]]; then
	echo "Dry run only. No commit created and nothing pushed."
	exit 0
fi

git commit -m "$COMMIT_MESSAGE" \
	-m "Source framework commit: $SOURCE_COMMIT"
echo "Pushing Salt Shack-only commit to $REMOTE branch $BRANCH"
git push origin "HEAD:refs/heads/$BRANCH"
