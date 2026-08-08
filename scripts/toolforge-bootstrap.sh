#!/usr/bin/env bash
# First-deploy helper for a new Buckbot Toolforge tool account.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

REPO_URL="${REPO_URL:-https://github.com/chuckthebuck/bucksaltbot2}"
BRANCH="${BRANCH:-main}"
TOOL_NAME="${TOOL_NAME:-buckbot}"
APPLY=0
CONFIGURE_ENV=0

usage() {
	# Describe the dry-run-first bootstrap and its independently gated mutations.
	cat <<'EOF'
Usage: bash scripts/toolforge-bootstrap.sh [options]

Prepare a new Toolforge Buckbot deployment. The default is a dry run; pass
--apply to make changes. Run this as the Toolforge tool account from a clean
checkout of this repository.

Options:
  --apply                 Build, initialize ToolsDB, update jobs.yaml, start web, and load jobs.
  --configure-env         Interactively create required secret envvars and set Buckbot defaults.
                          Use only on the first setup or an intentional secret rotation.
  --tool-name NAME        Toolforge tool name and Redis namespace (default: buckbot).
  --repo-url URL          Public Git repository to build.
  --branch REF            Git branch, tag, or commit to build (default: main).
  -h, --help              Show this help.

This script never reads secrets from files or command-line arguments. With
--configure-env, Toolforge prompts for each secret without echoing its value.
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--apply) APPLY=1; shift ;;
		--configure-env) CONFIGURE_ENV=1; shift ;;
		--tool-name) TOOL_NAME="$2"; shift 2 ;;
		--repo-url) REPO_URL="$2"; shift 2 ;;
		--branch) BRANCH="$2"; shift 2 ;;
		-h|--help) usage; exit 0 ;;
		*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
done

[[ "$TOOL_NAME" =~ ^[a-z][a-z0-9-]{0,62}$ ]] || {
	echo "--tool-name must be lowercase letters, numbers, and hyphens" >&2
	exit 2
}
[[ "$APPLY" == 1 || "$CONFIGURE_ENV" == 0 ]] || {
	echo "--configure-env requires --apply" >&2
	exit 2
}

run() {
	# Echo every command before executing so first-deploy logs remain auditable.
	printf '+ '
	printf '%q ' "$@"
	printf '\n'
	if [[ "$APPLY" == 1 ]]; then
		"$@"
	fi
}

require_cmd() {
	# Validate prerequisites before any optional Toolforge mutation begins.
	command -v "$1" >/dev/null 2>&1 || {
		echo "Missing required command: $1" >&2
		exit 127
	}
}

cd "$REPO_ROOT"
require_cmd git
require_cmd python3
require_cmd toolforge

if [[ -n "$(git status --porcelain)" ]]; then
	echo "Refusing to run from a dirty checkout; commit, stash, or remove local changes first." >&2
	exit 1
fi

IMAGE="tool-${TOOL_NAME}/tool-${TOOL_NAME}:latest"
GENERATED_JOBS_PATH="${TOOL_DATA_DIR:-$REPO_ROOT}/${TOOL_NAME}-generated-jobs.yaml"
INIT_JOB_NAME="${TOOL_NAME}-bootstrap-init"

echo "Tool:          $TOOL_NAME"
echo "Repository:    $REPO_URL @ $BRANCH"
echo "Build image:   $IMAGE"
echo "Generated YAML: $GENERATED_JOBS_PATH"
echo

if [[ "$CONFIGURE_ENV" == 1 ]]; then
	echo "Configuring non-secret Toolforge environment variables..."
	run toolforge envvars create BOT_NAME "$TOOL_NAME"
	run toolforge envvars create ENABLE_MODULE_LOADING 1
	run toolforge envvars create NOTDEV 1
	run toolforge envvars create BUCKBOT_REDIS_NAMESPACE "$TOOL_NAME"
	run toolforge envvars create BUCKBOT_CELERY_QUEUE "${TOOL_NAME}.celery"
	run toolforge envvars create BUCKBOT_CELERY_WORKER_NAME "${TOOL_NAME}-celery"

	echo "Toolforge will securely prompt for each required secret next."
	for variable in \
		SECRET_KEY \
		USER_OAUTH_CONSUMER_KEY \
		USER_OAUTH_CONSUMER_SECRET \
		CONSUMER_TOKEN \
		CONSUMER_SECRET \
		ACCESS_TOKEN \
		ACCESS_SECRET; do
		run toolforge envvars create "$variable"
	done
fi

echo "Starting build..."
run toolforge build start "$REPO_URL" --ref "$BRANCH" --use-latest-versions

echo "Initializing ToolsDB and generating module cron entries through the built image..."
run toolforge jobs run --wait --mount=all --image "$IMAGE" \
	--command "init-db --jobs-output $GENERATED_JOBS_PATH" "$INIT_JOB_NAME"

echo "Updating only the marked generated block in jobs.yaml..."
run python3 scripts/update_generated_jobs_yaml.py \
	--jobs jobs.yaml --generated "$GENERATED_JOBS_PATH"

echo "Starting the buildservice web process..."
run toolforge webservice buildservice start --mount=none

echo "Loading continuous workers and scheduled jobs..."
run toolforge jobs load jobs.yaml
run toolforge jobs list

if [[ "$APPLY" == 1 ]]; then
	echo
	echo "Generated module schedules are now loaded from this checkout."
	echo "Review and commit jobs.yaml before the next deployment:"
	echo "  git diff -- jobs.yaml"
	echo "  git add jobs.yaml && git commit -m 'chore: refresh Toolforge jobs'"
	echo "  git push"
else
	echo
	echo "Dry run only. Re-run with --apply after reviewing the commands."
fi
