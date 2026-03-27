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

# Live tests should exercise end-to-end execution without manual approval clicks.
os.environ.setdefault("LIVE_TEST_AUTO_APPROVE_REQUESTS", "1")
# Avoid writing production on-wiki status pages during integration tests.
os.environ.setdefault("LIVE_TEST_DISABLE_STATUS_UPDATES", "1")

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


# ── Live wiki edit ────────────────────────────────────────────────────────────

_ROLLBACK_TEST_PAGE = "User:Chuckbot/rollbacktest"
_NOOP_ROLLBACK_TEST_PAGE = "User:Chuckbot/rollbacktest-noop"


@pytest.fixture()
def live_wiki_edit(bot_site):
    """Make a real, uniquely-tagged edit to ``User:Chuckbot/rollbacktest``.

    The fixture is guarded by the ``LIVE_WIKI_EDITS`` environment variable.
    Set it to any non-empty value to enable tests that perform real wiki edits::

        LIVE_WIKI_EDITS=1 pytest tests/live/ -v -k rollback

    The fixture yields a four-tuple:

        (page_title, bot_username, original_text, test_marker)

    * ``page_title``   – the page that was edited (``User:Chuckbot/rollbacktest``)
    * ``bot_username`` – Wikimedia username of the bot account
    * ``original_text``– page wikitext *before* the test edit (used for teardown)
    * ``test_marker``  – unique HTML comment embedded in the test edit; its
                         presence/absence is used to verify rollback success

    **Teardown**: the page is restored to ``original_text`` regardless of
    whether the test passed or failed.  This prevents stale test edits from
    accumulating on the page between runs.
    """
    import time as _time

    import pywikibot

    if not os.environ.get("LIVE_WIKI_EDITS"):
        pytest.skip(
            "LIVE_WIKI_EDITS env var not set – skipping live wiki edit tests; "
            "set LIVE_WIKI_EDITS=1 to enable"
        )

    bot_username = bot_site.username()
    page = pywikibot.Page(bot_site, _ROLLBACK_TEST_PAGE)

    # Ensure the page exists with a stable baseline before the test edit so
    # there is always a prior revision to roll back to.
    original_text = page.text if page.exists() else ""
    if not original_text.strip():
        original_text = f"This page is used for automated rollback testing by [[User:{bot_username}]].\n"
        page.text = original_text
        page.save(
            summary="Chuckbot rollback test: initialise test page",
            minor=True,
            botflag=True,
        )

    # Make the test edit: append a uniquely-tagged section so we can confirm
    # the rollback removed it.
    test_marker = f"live-test-{int(_time.time() * 1000)}"
    page.text = original_text + f"\n<!-- {test_marker} -->\n"
    page.save(
        summary=f"Chuckbot rollback test: adding marker {test_marker}",
        minor=False,
        botflag=True,
    )

    yield _ROLLBACK_TEST_PAGE, bot_username, original_text, test_marker

    # ── Teardown ──────────────────────────────────────────────────────────────
    # Reload the page to get the latest revision.
    page = pywikibot.Page(bot_site, _ROLLBACK_TEST_PAGE)
    if page.text != original_text:
        page.text = original_text
        page.save(
            summary=f"Chuckbot rollback test: restoring page after marker {test_marker}",
            minor=True,
            botflag=True,
        )


# ── No-op rollback page ───────────────────────────────────────────────────────


@pytest.fixture()
def noop_rollback_page(bot_site):
    """Yield ``(page_title, bot_username)`` for a page whose sole author is the bot.

    ``User:Chuckbot/rollbacktest-noop`` is created by the bot on first use and
    never edited by anyone else.  Because the bot is the **only** author,
    rolling back the bot via the MediaWiki API always returns the ``onlyauthor``
    no-op error, making this fixture ideal for testing that such errors are
    treated as successful completions rather than failures.

    The fixture requires ``LIVE_WIKI_EDITS=1`` only when the page does not yet
    exist (the first run).  Subsequent runs reuse the existing page without
    additional edits.
    """
    import pywikibot

    bot_username = bot_site.username()
    page = pywikibot.Page(bot_site, _NOOP_ROLLBACK_TEST_PAGE)

    if not page.exists():
        if not os.environ.get("LIVE_WIKI_EDITS"):
            pytest.skip(
                "LIVE_WIKI_EDITS env var not set and no-op test page does not yet "
                "exist – set LIVE_WIKI_EDITS=1 to create it on first run"
            )
        page.text = (
            f"This page is used by automated tests to verify that no-op rollback "
            f"errors are handled gracefully.\n"
            f"It is maintained by [[User:{bot_username}]] and should not be edited "
            f"by anyone else.\n"
        )
        page.save(
            summary="Chuckbot: create no-op rollback test page",
            minor=True,
            botflag=True,
        )

    yield _NOOP_ROLLBACK_TEST_PAGE, bot_username
