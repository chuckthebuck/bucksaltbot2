"""Configuration for live integration tests.

These tests exercise the actual Toolforge infrastructure:
  - MySQL (tools-db, or TOOL_TOOLSDB_* environment variables)
  - Redis (TOOL_REDIS_URI, or the Toolforge default endpoint)
  - Celery worker (the ``celery_worker.py`` process must be running)
  - Bot OAuth credentials (CONSUMER_TOKEN, CONSUMER_SECRET, ACCESS_TOKEN, ACCESS_SECRET)

Every fixture skips automatically when a required service is unavailable, so
it is always safe to run the suite even in a partial environment.

Run only the live suite (recommended):
    pytest tests/live/ -v

Exclude the live suite from the regular unit-test run:
    pytest tests/ --ignore=tests/live/
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── Undo mocks injected by tests/conftest.py ─────────────────────────────────
#
# The parent conftest stubs out heavy dependencies so that unit tests never
# need live services.  Remove all of those stubs so this suite can import the
# real implementations.

_MOCKED = [
    "cnf",
    "redis",
    "pywikibot",
    "mwoauth",
    "mwoauth.flask",
]

# Modules that import from the stubs at import-time must also be cleared so
# they are re-imported against the real dependencies.
_DERIVED = [
    "app",
    "blueprint",
    "celery_init",
    "celery_worker",
    "editsummary",
    "pywikibot_utils",
    "redis_init",
    "redis_state",
    "rollback_queue",
    "router",
    "status_updater",
    "toolsdb",
]

for _mod in _MOCKED + _DERIVED:
    sys.modules.pop(_mod, None)


# ── Marker registration ───────────────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live: mark a test as a live integration test requiring Toolforge services",
    )


# ── Database ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def db_conn():
    """Open a live MySQL connection; skip when the database is unavailable."""
    try:
        from toolsdb import get_conn

        conn = get_conn()
        yield conn
        try:
            conn.close()
        except Exception:
            pass
    except Exception as exc:
        pytest.skip(f"MySQL unavailable – skipping live tests ({exc})")


# ── Redis ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def live_redis():
    """Return a live Redis client; skip when Redis is unreachable."""
    try:
        from redis_state import r

        r.ping()
        yield r
    except Exception as exc:
        pytest.skip(f"Redis unavailable – skipping live tests ({exc})")


# ── Flask app + test client ───────────────────────────────────────────────────


@pytest.fixture(scope="session")
def live_app():
    """Create the Flask app wired to real services."""
    try:
        import router  # noqa: F401 – registers routes as a side effect
        from app import flask_app

        flask_app.config["TESTING"] = True
        flask_app.config["SECRET_KEY"] = os.environ.get(
            "SECRET_KEY", "live-test-secret-key"
        )
        return flask_app
    except Exception as exc:
        pytest.skip(f"Flask app init failed – skipping live tests ({exc})")


@pytest.fixture()
def live_client(live_app):
    """Fresh test client per test (prevents session bleed)."""
    with live_app.test_client() as client:
        yield client


@pytest.fixture()
def admin_client(live_client, monkeypatch):
    """Test client with an active maintainer session.

    ``router.is_maintainer`` is patched to return ``True`` so that Toolhub is
    never consulted during the test.  The username is taken from the
    ``LIVE_TEST_USER`` environment variable (default: ``live-test-admin``).
    """
    import router as _router

    test_user = os.environ.get("LIVE_TEST_USER", "live-test-admin")
    monkeypatch.setattr(_router, "is_maintainer", lambda _u: True)

    with live_client.session_transaction() as sess:
        sess["username"] = test_user

    yield live_client, test_user


# ── Bot site ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def bot_site():
    """Authenticated pywikibot.Site; skipped when OAuth credentials are absent."""
    required = ["CONSUMER_TOKEN", "CONSUMER_SECRET", "ACCESS_TOKEN", "ACCESS_SECRET"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        pytest.skip(
            f"Bot OAuth credentials not set ({', '.join(missing)}) – skipping wiki tests"
        )
    try:
        import rollback_queue

        site = rollback_queue._bot_site()
        yield site
    except Exception as exc:
        pytest.skip(f"pywikibot auth failed – skipping wiki tests ({exc})")
