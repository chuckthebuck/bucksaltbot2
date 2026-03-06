"""Shared fixtures for bucksaltbot unit tests.

Heavy / unavailable dependencies (cnf, pywikibot, redis, mwoauth) are mocked
at the ``sys.modules`` level so that test modules can import the production
code without needing live services or configuration files.
"""
import os
import pathlib
import sys
from unittest.mock import MagicMock

# ── Must come before importing router.py, which checks NOTDEV at module level ─
os.environ.setdefault("NOTDEV", "1")

# ── Ensure the bucksaltbot package root is on sys.path ─────────────────────────
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# ── cnf ──────────────────────────────────────────────────────────────────────
_cnf_mock = MagicMock()
_cnf_mock.config = {"host": "localhost", "username": "testuser", "password": "testpass"}
sys.modules["cnf"] = _cnf_mock

# ── redis ─────────────────────────────────────────────────────────────────────
_redis_mock = MagicMock()
_redis_mock.Redis = MagicMock(return_value=MagicMock())
sys.modules.setdefault("redis", _redis_mock)

# ── pywikibot ─────────────────────────────────────────────────────────────────
sys.modules.setdefault("pywikibot", MagicMock())

# ── mwoauth ───────────────────────────────────────────────────────────────────
sys.modules.setdefault("mwoauth", MagicMock())
sys.modules.setdefault("mwoauth.flask", MagicMock())
