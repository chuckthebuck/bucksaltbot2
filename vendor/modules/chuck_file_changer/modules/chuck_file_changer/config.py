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
REPOSITORY_URL = "https://github.com/chuckthebuck/chuck-file-changer"
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


def default_user_agent() -> str:
    return (
        f"ChuckFileChanger/{module_version()} "
        f"({REPOSITORY_URL}; User:Alachuckthebuck)"
    )


DEFAULT_USER_AGENT = default_user_agent()


def user_agent() -> str:
    return (
        os.getenv("CHUCK_FILE_CHANGER_USER_AGENT", "").strip()
        or os.getenv("CHUCK_FILE_CHANGER_HTTP_USER_AGENT", "").strip()
        or DEFAULT_USER_AGENT
    )


def http_headers() -> dict[str, str]:
    return {"User-Agent": user_agent()}
