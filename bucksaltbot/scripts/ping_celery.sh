#!/usr/bin/env bash
celery -A matchandsplit.celery_app inspect ping -d worker@mas-sodium