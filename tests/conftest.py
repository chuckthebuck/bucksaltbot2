"""Shared fixtures for bucksaltbot unit tests.

Heavy / unavailable dependencies (cnf, pywikibot, redis, mwoauth) are mocked
at the ``sys.modules`` level so that test modules can import the production
code without needing live services or configuration files.
"""

import os
import pathlib
import sys
from unittest.mock import MagicMock

import pytest

# ── Must come before importing router.py, which checks NOTDEV at module level ─
os.environ.setdefault("NOTDEV", "1")
os.environ["ENABLE_MODULE_LOADING"] = "0"
os.environ.setdefault("BOT_ADMIN_ACCOUNTS", "chuckbot")
os.environ.setdefault(
    "ROLLBACK_CONTROL_JSON",
    (
        '{"Alice":["group:basic"],'
        '"Chuckbot":["group:admin"],'
        '"Statusbot":["group:basic"],'
        '"status-site":["group:basic"]}'
    ),
)

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


@pytest.fixture(autouse=True)
def _isolate_external_authz_and_module_access(monkeypatch, request):
    """Keep unit tests hermetic unless a test explicitly patches live behavior."""
    if request.node.path.name == "test_authz.py":
        return

    import app
    import router
    import router.authz as authz
    import router.routes as routes

    monkeypatch.setattr(app, "get_toolhub_maintainers", lambda: {"maintainer"})

    for module in (router, authz, routes):
        monkeypatch.setattr(module, "get_user_groups", lambda *_args, **_kwargs: [], raising=False)
        monkeypatch.setattr(module, "get_user_global_groups", lambda *_args, **_kwargs: [], raising=False)
        monkeypatch.setattr(module, "get_project_user_groups", lambda *_args, **_kwargs: [], raising=False)
        monkeypatch.setattr(module, "get_global_userright_groups", lambda *_args, **_kwargs: [], raising=False)
        monkeypatch.setattr(module, "get_project_userright_groups", lambda *_args, **_kwargs: [], raising=False)

    monkeypatch.setattr(routes, "list_module_definitions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        routes,
        "user_has_module_access",
        lambda *_args, **kwargs: bool(kwargs.get("is_maintainer")),
    )
