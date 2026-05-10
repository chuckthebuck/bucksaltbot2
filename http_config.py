"""HTTP request configuration shared by the framework."""

from __future__ import annotations

import os

HTTP_USER_AGENT = (
    "Buckbot/4.0 (https://github.com/chuckthebuck/bucksaltbot2; User:Alachuckthebuck)"
)


def framework_http_user_agent() -> str:
    return os.getenv("BUCKBOT_HTTP_USER_AGENT", HTTP_USER_AGENT)


def http_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"User-Agent": framework_http_user_agent()}
    if extra:
        headers.update(extra)
    return headers
