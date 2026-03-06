#!/usr/bin/env bash
PORT=${PORT:-8000}

gunicorn -w 4 -b 0.0.0.0:$PORT router:app --timeout 600 --access-logfile -
