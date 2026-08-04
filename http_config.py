"""HTTP request configuration shared by the framework."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

REPOSITORY_URL = "https://github.com/chuckthebuck/bucksaltbot2"
DEFAULT_VERSION = "0.0.0"


@lru_cache(maxsize=1)
def framework_version() -> str:
    """Read and cache the checked-in framework version for request identity."""
    version_file = Path(__file__).resolve().with_name("VERSION")
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_VERSION
    return version or DEFAULT_VERSION


def default_framework_http_user_agent() -> str:
    """Build the Wikimedia-compliant default User-Agent string."""
    return (
        f"Buckbot/{framework_version()} "
        f"({REPOSITORY_URL}; User:Alachuckthebuck)"
    )


def framework_http_user_agent() -> str:
    """Return an operator override or the versioned default User-Agent."""
    return os.getenv("BUCKBOT_HTTP_USER_AGENT", "").strip() or default_framework_http_user_agent()


def http_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return standard outbound headers merged with request-specific values."""
    headers = {"User-Agent": framework_http_user_agent()}
    if extra:
        headers.update(extra)
    return headers
