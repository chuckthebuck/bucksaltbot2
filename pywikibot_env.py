"""Shared Pywikibot environment bootstrapping helpers."""

from __future__ import annotations

import os
from pathlib import Path

from botconfig import BOT_USERNAME as _BOT_USERNAME

_DEFAULT_BOT_USERNAME = _BOT_USERNAME


def _desired_user_config(bot_username: str) -> str:
    """Return a minimal but OAuth-capable Pywikibot user-config.py."""
    return (
        "import os\n\n"
        "family = 'commons'\n"
        "mylang = 'commons'\n"
        f"usernames['commons']['commons'] = '{bot_username}'\n\n"
        "if all(\n"
        "    os.getenv(name)\n"
        "    for name in ('CONSUMER_TOKEN', 'CONSUMER_SECRET', 'ACCESS_TOKEN', 'ACCESS_SECRET')\n"
        "):\n"
        "    authenticate['commons.wikimedia.org'] = (\n"
        "        os.getenv('CONSUMER_TOKEN'),\n"
        "        os.getenv('CONSUMER_SECRET'),\n"
        "        os.getenv('ACCESS_TOKEN'),\n"
        "        os.getenv('ACCESS_SECRET'),\n"
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
            # Detect legacy OAuth variables - any assignment style, not just os.getenv
            has_legacy_oauth_vars = any(
                marker in current
                for marker in (
                    "consumer_key",
                    "consumer_secret",
                    "access_token",
                    "access_secret",
                )
            )
            # Check desired config is minimal and complete
            has_all_desired_keys = all(
                key in current
                for key in (
                    "family = 'commons'",
                    "mylang = 'commons'",
                    "usernames['commons']['commons']",
                    "authenticate['commons.wikimedia.org']",
                )
            )

            # Rewrite if: legacy vars present, OR auth incomplete, OR config is too old
            if has_legacy_oauth_vars or not has_all_desired_keys:
                config_file.write_text(desired, encoding="utf-8")

        return pywikibot_home
    except Exception:
        if strict:
            raise
        return None
