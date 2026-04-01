"""Central identity and configuration constants for the bot framework.

All bot-specific identity is read from environment variables here and exposed
as module-level constants so that individual modules never scatter hardcoded
bot names or URLs.  Override any constant by setting the corresponding
environment variable before the application starts.
"""

import os

# ── Bot & tool identity ───────────────────────────────────────────────────────

# Short lowercase identifier used in Redis key prefixes, default Toolhub ID,
# and any place a machine-readable bot name is needed.
# Example: BOT_NAME=mytoolbot
BOT_NAME: str = os.getenv("BOT_NAME", "buckbot")

# The MediaWiki account username that the bot edits with (capitalised, as it
# appears on the wiki).
# Example: BOT_USERNAME=MyToolBot
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "Chuckbot")

# The human operator / help page on the wiki.  Used in talk-page notices and
# status-page messages.
# Example: BOT_HELP_PAGE=OperatorUsername
BOT_HELP_PAGE: str = os.getenv("BOT_HELP_PAGE", "Alachuckthebuck")

# Wiki page URL for end-user documentation.  Displayed in the tool's nav.
# Example: BOT_DOCUMENTATION_URL=https://commons.wikimedia.org/wiki/Help:MyTool
BOT_DOCUMENTATION_URL: str = os.getenv(
    "BOT_DOCUMENTATION_URL",
    f"https://commons.wikimedia.org/wiki/User:Alachuckthebuck/unbuckbot",
)

# Primary account allowed to edit runtime config via the admin API.  Typically
# the same as BOT_NAME or the operator's bot account.
# Example: CONFIG_EDIT_PRIMARY_ACCOUNT=mytoolbot
BOT_ADMIN_PRIMARY_ACCOUNT: str = (
    os.getenv("CONFIG_EDIT_PRIMARY_ACCOUNT", "chuckbot").strip().lower()
)

# ── Toolforge / Toolhub ───────────────────────────────────────────────────────

# The Toolhub tool slug used to look up maintainers.  Defaults to BOT_NAME.
# Example: TOOLHUB_TOOL_ID=mybotname
TOOLHUB_TOOL_ID: str = os.getenv("TOOLHUB_TOOL_ID", BOT_NAME)

# Full Toolhub API URL.  Computed from TOOLHUB_TOOL_ID by default; set this
# env var to override the entire URL (e.g. for bots not registered on Toolhub).
# Example: TOOLHUB_API_URL=https://toolhub.wikimedia.org/api/tools/mybotname/
TOOLHUB_API_URL: str = os.getenv(
    "TOOLHUB_API_URL",
    f"https://toolhub.wikimedia.org/api/tools/{TOOLHUB_TOOL_ID}/",
)

# The Toolforge tool name used to build the OAuth callback URL.
# Example: TOOL_NAME=mybotname
TOOL_NAME: str = os.getenv("TOOL_NAME", BOT_NAME)

# ── Wiki / MediaWiki API ──────────────────────────────────────────────────────

# Base URL of the MediaWiki Action API for the target wiki.
# Example: WIKI_API_URL=https://en.wikipedia.org/w/api.php
WIKI_API_URL: str = os.getenv(
    "WIKI_API_URL", "https://commons.wikimedia.org/w/api.php"
)

# Comma-separated list of origins allowed for CORS on the /api/* endpoints.
# Example: CORS_ALLOWED_ORIGINS=https://commons.wikimedia.org,https://en.wikipedia.org
_cors_raw: str = os.getenv(
    "CORS_ALLOWED_ORIGINS", "https://commons.wikimedia.org"
)
CORS_ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in _cors_raw.split(",") if o.strip()
]

# ── Database ──────────────────────────────────────────────────────────────────

# Suffix appended to the Toolforge database username to form the database name.
# The database name is always <toolforge_user>__<DB_NAME_SUFFIX>.
# Changing this renames the database; use the migration script for existing data.
# Example: DB_NAME_SUFFIX=my_tool_db
DB_NAME_SUFFIX: str = os.getenv("DB_NAME_SUFFIX", "match_and_split")

# ── Status page ───────────────────────────────────────────────────────────────

# Prefix for the on-wiki status subpages edited by the bot.
# Defaults to User:<BOT_USERNAME>/status.
# Example: STATUS_PAGE_PREFIX=User:MyToolBot/status
STATUS_PAGE_PREFIX: str = os.getenv(
    "STATUS_PAGE_PREFIX", f"User:{BOT_USERNAME}/status"
)

# ── Edit summary ─────────────────────────────────────────────────────────────

# Edit summaries appended by pywikibot_utils.safe_put() when editing pages.
# Provide localised overrides via env vars.
EDIT_SUMMARY_EN: str = os.getenv(
    "EDIT_SUMMARY_EN",
    "automated match and split edit, revert if incorrect"
    "  ([[Wikisource:Scriptorium#SodiumBot|bot request]])",
)
EDIT_SUMMARY_DEFAULT: str = os.getenv(
    "EDIT_SUMMARY_DEFAULT",
    "automated match and split edit, revert if incorrect",
)
