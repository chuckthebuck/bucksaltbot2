#!/usr/bin/env bash
set -euo pipefail

echo "Starting development environment"
mkdir -p "${TOOL_DATA_DIR:-./data}/logs" "${PYWIKIBOT_DIR:-./data/pywikibot}"

npm run dev &
gunicorn -w 2 -b "0.0.0.0:${PORT:-8000}" app:flask_app --timeout 600 --access-logfile - --reload --reload-extra-file ./templates/ &
wait
