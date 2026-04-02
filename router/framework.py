"""Bot framework: extension points for building new bots on top of this package.

The ``router`` package is structured as a reusable framework for building
Wiki-bot web applications.  It is split into generic and bot-specific layers:

Generic (reusable) modules
--------------------------
:mod:`router.authz`
    MediaWiki group lookups, runtime configuration, user-grant expansion.
    Depends only on :mod:`app` (Flask app + ``is_maintainer``) via the
    ``_r()`` hook pattern — replaceable per-bot.

:mod:`router.permissions`
    Per-user permission evaluation.  Calls ``is_maintainer``, ``is_tester``,
    and ``_effective_runtime_authz_config`` through ``_r()`` so they can be
    swapped out for a different bot's implementations.

:mod:`router.diff_state`
    Redis-backed job state helpers (diff payloads, error keys, stale-job
    detection).  Generic except for the Redis key prefix (``rollback:``).

:mod:`router.wiki_api`
    MediaWiki API wrappers (diff metadata, account contributions, timestamps).
    No bot-specific logic.

Bot-specific modules
--------------------
:mod:`router.jobs`
    Job constants, creation helpers, and Celery task wiring specific to the
    BuckSaltBot rollback use-case.

:mod:`router.routes`
    Flask route handlers specific to the BuckSaltBot rollback workflow.

Extension guide
---------------
To build a new bot on top of this framework:

1. Create your own ``app.py`` exposing at minimum:

   - ``flask_app``: a :class:`flask.Flask` instance
   - ``BOT_ADMIN_ACCOUNTS``: a ``frozenset[str]`` of privileged account names
   - ``is_maintainer(username: str) -> bool``: returns ``True`` when the given
     user should have maintainer-level rights
   - ``MAX_JOB_ITEMS``: maximum number of items per rollback job

2. Create ``jobs.py`` with bot-specific job types, Celery tasks, and
   constants.

3. Create ``routes.py`` registering your Flask endpoints.  Import the generic
   helpers from :mod:`router.authz`, :mod:`router.permissions`, and
   :mod:`router.wiki_api` as needed.

4. Create ``router/__init__.py`` that re-exports your public surface (mirrors
   the existing one) so tests can patch ``router.X``.

The ``_r()`` helper
-------------------
Throughout the framework modules, patchable singletons are accessed via a
small ``_r()`` helper::

    def _r():
        import sys
        return sys.modules.get('router')

Any attribute ``X`` on the top-level ``router`` module shadows the local
default.  This lets tests (and bot authors) patch behaviour at the
``router.X`` level without touching the underlying module.

Naming conventions
------------------
- ``_user_permissions(username)`` → ``frozenset[str]`` of permission flags
- ``_effective_runtime_authz_config()`` → current runtime config dict
- ``is_maintainer(username)`` → bool (bot-specific override)
- ``is_tester(username)`` → bool (optional, defaults to ``False``)
- ``BOT_ADMIN_ACCOUNTS`` → ``frozenset[str]`` (highest privilege accounts)
"""
