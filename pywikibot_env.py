"""Shared Pywikibot environment bootstrapping helpers."""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_BOT_USERNAME = "Chuckbot"


def _desired_user_config(bot_username: str) -> str:
    """Return a minimal but OAuth-capable Pywikibot user-config.py."""
    return (
        "import os\n\n"
        "family = 'commons'\n"
        "mylang = 'commons'\n"
        f"usernames['commons']['commons'] = '{bot_username}'\n\n"
        "consumer_key = os.getenv('CONSUMER_TOKEN')\n"
        "consumer_secret = os.getenv('CONSUMER_SECRET')\n"
        "access_token = os.getenv('ACCESS_TOKEN')\n"
        "access_secret = os.getenv('ACCESS_SECRET')\n\n"
        "if all([consumer_key, consumer_secret, access_token, access_secret]):\n"
        "    authenticate['commons.wikimedia.org'] = (\n"
        "        consumer_key,\n"
        "        consumer_secret,\n"
        "        access_token,\n"
        "        access_secret,\n"
        "    )\n"
    )


def resolve_pywikibot_dir() -> Path:
    """Return a writable directory for Pywikibot config files."""
    candidates: list[Path] = []

    env_dir = os.environ.get("PYWIKIBOT_DIR")
    if env_dir:
        candidates.append(Path(env_dir))

    home = os.environ.get("HOME")
    if home and home != "/":
        candidates.append(Path(home) / ".pywikibot")

    candidates.append(Path("/workspace") / ".pywikibot")
    candidates.append(Path("/tmp") / f".pywikibot-{os.getuid()}")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue

    raise RuntimeError("No writable directory available for PYWIKIBOT_DIR")


def ensure_pywikibot_env(
    *,
    bot_username: str = _DEFAULT_BOT_USERNAME,
    strict: bool = True,
) -> Path | None:
    """Set PYWIKIBOT_DIR and ensure a minimal user-config.py exists.

    When strict is False, errors are swallowed and None is returned.
    """
    try:
        pywikibot_home = resolve_pywikibot_dir()
        os.environ["PYWIKIBOT_DIR"] = str(pywikibot_home)

        config_file = pywikibot_home / "user-config.py"
        desired = _desired_user_config(bot_username)

        if not config_file.exists():
            config_file.write_text(desired, encoding="utf-8")
        else:
            current = config_file.read_text(encoding="utf-8")
            has_auth = "authenticate['commons.wikimedia.org']" in current
            minimal_legacy = (
                "family = 'commons'" in current
                and "mylang = 'commons'" in current
                and "usernames['commons']['commons']" in current
                and "consumer_key = os.getenv" not in current
            )

            if minimal_legacy and not has_auth:
                config_file.write_text(desired, encoding="utf-8")

        return pywikibot_home
    except Exception:
        if strict:
            raise
        return None
