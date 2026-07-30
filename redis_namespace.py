"""Names used to keep one Buckbot deployment isolated in shared Redis."""

from __future__ import annotations

import os
import re


_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def _configured_name(variable: str, default: str) -> str:
    value = os.getenv(variable, default).strip() or default
    if not _NAME_RE.fullmatch(value):
        raise RuntimeError(
            f"{variable} must contain only letters, numbers, dots, underscores, and hyphens"
        )
    return value


def redis_namespace() -> str:
    """Return the deployment-specific prefix for all Buckbot Redis keys."""
    return _configured_name("BUCKBOT_REDIS_NAMESPACE", "buckbot")


def celery_queue_name() -> str:
    """Return the sole Celery queue consumed by this Buckbot deployment."""
    return _configured_name("BUCKBOT_CELERY_QUEUE", f"{redis_namespace()}.celery")
