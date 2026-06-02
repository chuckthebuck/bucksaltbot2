"""HTTP request configuration shared by the framework."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

REPOSITORY_URL = "https://github.com/chuckthebuck/bucksaltbot2"
DEFAULT_VERSION = "0.0.0"


@lru_cache(maxsize=1)
def framework_version() -> str:
    version_file = Path(__file__).resolve().with_name("VERSION")
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_VERSION
    return version or DEFAULT_VERSION


def default_framework_http_user_agent() -> str:
    return (
        f"Buckbot/{framework_version()} "
        f"({REPOSITORY_URL}; User:Alachuckthebuck)"
    )


def framework_http_user_agent() -> str:
    return os.getenv("BUCKBOT_HTTP_USER_AGENT", "").strip() or default_framework_http_user_agent()


def http_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"User-Agent": framework_http_user_agent()}
    if extra:
        headers.update(extra)
    return headers
