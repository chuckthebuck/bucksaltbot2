"""Runtime configuration for the Four Award module."""

from __future__ import annotations

from functools import lru_cache
from importlib import metadata
import os
from pathlib import Path
import tomllib

WIKI_CODE = os.getenv("FOUR_AWARD_WIKI_CODE", "en")
WIKI_FAMILY = os.getenv("FOUR_AWARD_WIKI_FAMILY", "wikipedia")
WIKI_API_URL = os.getenv(
    "FOUR_AWARD_WIKI_API_URL",
    f"https://{WIKI_CODE}.wikipedia.org/w/api.php",
)
PACKAGE_NAME = "chuck-the-4awardhelper"
REPOSITORY_URL = "https://github.com/chuckthebuck/module4awardhelper"
DEFAULT_VERSION = "0.0.0"


def _pyproject_version() -> str | None:
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if not pyproject.exists():
            continue
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        version = data.get("project", {}).get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    return None


@lru_cache(maxsize=1)
def module_version() -> str:
    local_version = _pyproject_version()
    if local_version:
        return local_version
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return DEFAULT_VERSION


def default_http_user_agent() -> str:
    return (
        f"FourAwardHelper/{module_version()} "
        f"(User:Alachuckthebuck; {REPOSITORY_URL})"
    )


HTTP_USER_AGENT = os.getenv("FOUR_AWARD_HTTP_USER_AGENT", "").strip() or default_http_user_agent()
FOUR_PAGE = os.getenv("FOUR_AWARD_PAGE", "Wikipedia:Four Award")
RECORDS_PAGE = os.getenv("FOUR_AWARD_RECORDS_PAGE", "Wikipedia:Four Award/Records")
LEADERBOARD_PAGE = os.getenv("FOUR_AWARD_LEADERBOARD_PAGE", "Wikipedia:Four Award/Leaderboard")
BOT_MARKER_PREFIX = "FourAwardBot"
EDIT_TAG_LINK = "[[User:Alachuckthebuck/FourAwardHelper|FourAwardHelper]]"
DEFAULT_BRFA_TASK = os.getenv("FOUR_AWARD_BRFA_TASK", "").strip()
DEFAULT_EDIT_SUMMARY_SUFFIX = os.getenv("FOUR_AWARD_EDIT_SUMMARY_SUFFIX", EDIT_TAG_LINK).strip()
BRFA_TASK = DEFAULT_BRFA_TASK
EDIT_SUMMARY_SUFFIX = DEFAULT_EDIT_SUMMARY_SUFFIX

# Default to dry-run so framework/module config has to opt into live writes.
ENABLED = os.getenv("FOUR_AWARD_ENABLED", "1") == "1"
DRY_RUN = os.getenv("FOUR_AWARD_DRY_RUN", "1") == "1"
ENABLE_REPLIES = os.getenv("FOUR_AWARD_ENABLE_REPLIES", "1") == "1"
ENABLE_RECORDS = os.getenv("FOUR_AWARD_ENABLE_RECORDS", "1") == "1"
ENABLE_REMOVAL = os.getenv("FOUR_AWARD_ENABLE_REMOVAL", "1") == "1"
ENABLE_TALK_NOTICES = os.getenv("FOUR_AWARD_ENABLE_TALK_NOTICES", "1") == "1"
ENABLE_ARTICLE_HISTORY = os.getenv("FOUR_AWARD_ENABLE_ARTICLE_HISTORY", "1") == "1"
ENABLE_LEADERBOARD = os.getenv("FOUR_AWARD_ENABLE_LEADERBOARD", "0") == "1"
ALLOW_AUTOMATED_APPROVAL = os.getenv("FOUR_AWARD_ALLOW_AUTOMATED_APPROVAL", "0") == "1"
IGNORE_EXISTING_RECORDS = os.getenv("FOUR_AWARD_IGNORE_EXISTING_RECORDS", "0") == "1"
AWARD_DATE_OVERRIDE = os.getenv("FOUR_AWARD_AWARD_DATE")
DRY_RUN_REPORT_PAGE = os.getenv("FOUR_AWARD_DRY_RUN_REPORT_PAGE", "")
PUBLISH_DRY_RUN_REPORT = os.getenv("FOUR_AWARD_PUBLISH_DRY_RUN_REPORT", "0") == "1"

MAX_NOMINATIONS_PER_RUN = int(os.getenv("FOUR_AWARD_MAX_NOMINATIONS_PER_RUN", "25"))
