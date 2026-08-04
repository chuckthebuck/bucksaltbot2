#!/usr/bin/env bash
# Start the legacy Vite build watcher and reloadable Gunicorn process.
# Debug templates still need a separate real Vite server on port 5173.
set -euo pipefail

echo "Starting development environment"
mkdir -p "${TOOL_DATA_DIR:-./data}/logs" "${PYWIKIBOT_DIR:-./data/pywikibot}"

npm run dev &
gunicorn -w 2 -b "0.0.0.0:${PORT:-8000}" app:flask_app --timeout 600 --access-logfile - --reload --reload-extra-file ./templates/ &
wait
