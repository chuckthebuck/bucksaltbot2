#!/usr/bin/env bash
set -e

celery -A celery_init inspect ping
