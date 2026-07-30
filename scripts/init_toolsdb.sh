#!/usr/bin/env bash
# Initialize the ToolsDB schema, register enabled modules, and optionally emit
# their current Toolforge cron entries. Intended for a one-off buildservice job.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

usage() {
	cat <<'EOF'
Usage: bash scripts/init_toolsdb.sh [--jobs-output PATH]

Creates/upgrades Buckbot's ToolsDB tables and registers all enabled module
manifests. With --jobs-output, writes the generated module cron-job YAML to
PATH. The output contains only generated module entries; merge it into the
marked block in jobs.yaml with scripts/update_generated_jobs_yaml.py.
EOF
}

jobs_output=""
while [[ $# -gt 0 ]]; do
	case "$1" in
		--jobs-output)
			[[ $# -ge 2 ]] || { echo "--jobs-output requires a path" >&2; exit 2; }
			jobs_output="$2"
			shift 2
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
done

export NOTDEV="${NOTDEV:-1}"
export ENABLE_MODULE_LOADING="${ENABLE_MODULE_LOADING:-1}"

python - "$jobs_output" <<'PY'
from __future__ import annotations

from pathlib import Path
import sys

from toolsdb import init_db

# Run schema DDL first so a connection error is reported clearly before module
# bootstrap. Importing app then persists enabled local and vendored manifests.
init_db()
import app  # noqa: F401,E402

from jobs_yaml_generator import generate_jobs_yaml_section  # noqa: E402
from router.module_registry import list_module_definitions  # noqa: E402

output_path = sys.argv[1]
modules = list_module_definitions(enabled_only=True)
print("Initialized ToolsDB and registered enabled modules:", ", ".join(
    record.definition.name for record in modules
) or "(none)")

if output_path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(generate_jobs_yaml_section(), encoding="utf-8")
    print(f"Wrote generated module jobs to {destination}")
PY
