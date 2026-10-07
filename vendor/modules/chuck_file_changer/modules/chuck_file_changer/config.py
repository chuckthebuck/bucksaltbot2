"""Resolve Commons coordinates, package version, and outbound HTTP identity.

Both requests and Pywikibot use the same module-specific User-Agent policy.
Deployment overrides are read at call time, while the packaged default embeds
the best available distribution or source-tree version.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import metadata
import os
from pathlib import Path
import tomllib

COMMONS_SITE_CODE = "commons"
COMMONS_SITE_FAMILY = "commons"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
PACKAGE_NAME = "chuck-file-changer"
REPOSITORY_URL = "https://github.com/chuckthebuck/Chuckthefilechange"
DEFAULT_VERSION = "0.0.0"


def _pyproject_version() -> str | None:
    """Find the nearest source-tree project version for editable checkouts."""
    # Installed wheels need not contain pyproject.toml. Walking parents first
    # keeps local development aligned with the source currently being tested.
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
    """Return a cached source, installed-package, or safe fallback version."""
    local_version = _pyproject_version()
    if local_version:
        return local_version
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return DEFAULT_VERSION


def default_user_agent() -> str:
    """Build the identifying default required for Wikimedia HTTP traffic."""
    return (
        f"ChuckFileChanger/{module_version()} "
        f"({REPOSITORY_URL}; User:Alachuckthebuck)"
    )


# Freeze the default once; explicit environment overrides remain dynamic below.
DEFAULT_USER_AGENT = default_user_agent()


def user_agent() -> str:
    """Return the first nonblank deployment override or packaged default.

    The primary variable is module-specific. The older HTTP-suffixed name is
    retained as a lower-priority compatibility alias.
    """
    return (
        os.getenv("CHUCK_FILE_CHANGER_USER_AGENT", "").strip()
        or os.getenv("CHUCK_FILE_CHANGER_HTTP_USER_AGENT", "").strip()
        or DEFAULT_USER_AGENT
    )


def http_headers() -> dict[str, str]:
    """Return fresh request headers so environment overrides apply per call."""
    return {"User-Agent": user_agent()}
