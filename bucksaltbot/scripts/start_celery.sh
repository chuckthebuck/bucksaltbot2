#!/usr/bin/env bash
id
cat user-config.tmpl > user-config.py
ls -lah user-config.py
celery -A matchandsplit.celery_app worker --loglevel INFO --concurrency=20 -n worker@mas-sodium