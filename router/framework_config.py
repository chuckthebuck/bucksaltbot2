"""Shared, environment-driven router framework configuration."""

import os

BOT_NAME = os.getenv("BOT_NAME") or os.getenv("TOOL_NAME") or "buckbot"

REDIS_KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "rollback").strip() or "rollback"

WIKI_API_URL = os.getenv("WIKI_API_URL", "https://commons.wikimedia.org/w/api.php")
MWOAUTH_BASE_URL = os.getenv("MWOAUTH_BASE_URL", "https://meta.wikimedia.org")
MWOAUTH_INDEX_URL = os.getenv(
    "MWOAUTH_INDEX_URL", "https://meta.wikimedia.org/w/index.php"
)

DOCS_URL = os.getenv(
    "BOT_DOCS_URL",
    "https://wikitech.wikimedia.org/wiki/Tool:Buckbot",
)

UNAUTHORIZED_MESSAGE = os.getenv(
    "UNAUTHORIZED_MESSAGE",
    "This tool is restricted to Commons admins and maintainers.",
)

ALLOWED_GROUPS = {
    g.strip().lower()
    for g in os.getenv("ALLOWED_GROUPS", "sysop,rollbacker").split(",")
    if g.strip()
}

WORKER_HEARTBEAT_KEY = f"{REDIS_KEY_PREFIX}:worker:heartbeat"
RATE_LIMIT_KEY_PREFIX = f"{REDIS_KEY_PREFIX}:ratelimit"
DIFF_PAYLOAD_KEY_PREFIX = f"{REDIS_KEY_PREFIX}:diff:payload"
DIFF_ERROR_KEY_PREFIX = f"{REDIS_KEY_PREFIX}:diff:error"


def oauth_callback_url() -> str:
    configured = os.environ.get("USER_OAUTH_CALLBACK_URL")
    if configured:
        return configured
    return f"https://{BOT_NAME}.toolforge.org/mas-oauth-callback"
