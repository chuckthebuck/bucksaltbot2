#!/usr/bin/env bash
set -e

celery -A celery_worker:app inspect ping --timeout=10
