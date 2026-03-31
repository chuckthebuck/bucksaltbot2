"""Shared Pywikibot environment bootstrapping helpers."""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_BOT_USERNAME = "Chuckbot"


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
        if not config_file.exists():
            config_file.write_text(
                "family = 'commons'\n"
                "mylang = 'commons'\n"
                f"usernames['commons']['commons'] = '{bot_username}'\n",
                encoding="utf-8",
            )

        return pywikibot_home
    except Exception:
        if strict:
            raise
        return None
