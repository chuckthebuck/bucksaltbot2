#!/usr/bin/env bash
set -e

celery -A app:celery inspect ping
