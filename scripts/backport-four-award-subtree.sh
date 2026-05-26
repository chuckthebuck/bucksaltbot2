#!/usr/bin/env bash
set -euo pipefail

REMOTE="${FOUR_AWARD_REMOTE:-https://github.com/chuckthebuck/module4awardhelper.git}"
BRANCH="${FOUR_AWARD_BRANCH:-framework-dev}"
PREFIX="vendor/modules/four_award"

if [[ "${1:-}" == "--dry-run" ]]; then
	DRY_RUN=1
else
	DRY_RUN=0
fi

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
	echo "Not inside a git repository." >&2
	exit 1
fi

cd "$(git rev-parse --show-toplevel)"

if [[ ! -d "$PREFIX" ]]; then
	echo "Missing subtree prefix: $PREFIX" >&2
	exit 1
fi

split_commit="$(git subtree split --prefix="$PREFIX")"

for forbidden in app.py router Deployment-docs vendor requirements.txt requirements-modules.txt enabled-modules.txt; do
	if git cat-file -e "${split_commit}:${forbidden}" 2>/dev/null; then
		echo "Refusing to push: split commit contains framework path '$forbidden'." >&2
		echo "Split commit was: $split_commit" >&2
		exit 1
	fi
done

echo "4Award split commit: $split_commit"
echo "Root files that will be pushed:"
git ls-tree --name-only "$split_commit"

if [[ "$DRY_RUN" == "1" ]]; then
	echo "Dry run only. Nothing pushed."
	exit 0
fi

echo "Pushing $split_commit to $REMOTE branch $BRANCH"
git push "$REMOTE" "$split_commit:refs/heads/$BRANCH"
