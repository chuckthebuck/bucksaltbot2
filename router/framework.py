"""Current architecture map for the Chuck the Buckbot framework.

The application now has two extension layers.  Core rollback behavior still
lives in the host application, while additional tools are declared as modules
with validated manifests.  The old flow of copying ``app.py``, ``jobs.py``, and
``routes.py`` to create a separate bot is no longer the supported extension
path.

Startup and compatibility facade
--------------------------------
``app.py`` constructs Flask and Celery, then imports :mod:`router`.  The package
initializer re-exports historically public helpers because workers and tests
still call or patch ``router.X``.  It imports :mod:`router.routes` last, after
those compatibility names exist, to avoid decorator-time circular imports.
Helpers that use ``_r()`` deliberately resolve this assembled package at call
time; that seam is retained for compatibility, not as a plugin API.

When module loading is enabled, startup reads ``enabled-modules.txt`` plus the
``ENABLED_MODULES`` environment override, discovers local and installed-package
manifests, persists their definitions, and registers enabled Flask blueprints.
The allowlist contains module names only.  Python packages are vendored/pinned
in ``requirements-modules.txt`` and installed with the application image;
runtime cloning or remote module installation is intentionally unsupported.

Core framework boundaries
-------------------------
:mod:`router.framework_config`
    Environment-backed deployment constants and URL/key-prefix helpers.

:mod:`router.authz`
    Runtime authorization configuration, explicit/role/automatic grant
    expansion, MediaWiki group lookups, and canonical module-right atoms.

:mod:`router.permissions`
    Converts identity and grant atoms into route-facing capabilities such as
    read, write, review, configuration, and module administration.

:mod:`router.module_registry`
    Validates JSON/TOML manifests; persists module definitions, mutable cron
    settings, access grants, non-secret configuration, and job-run lifecycle
    rows; and enforces durable job concurrency policies.

:mod:`router.module_runtime`
    Imports trusted enabled packages and registers optional web blueprints.
    Blueprint imports happen in the Flask process and are not sandboxed.

:mod:`router.module_schedule` and :mod:`router.module_estop`
    Translate supported human schedules to cron, and coordinate durable run
    cancellation with process/platform emergency-stop attempts.

:mod:`router.wiki_api` and :mod:`router.wiki_actions`
    Provide MediaWiki reads plus the constrained declarative write-action
    catalog shared by core and module jobs.

:mod:`router.diff_state`, :mod:`router.jobs`, and :mod:`router.routes`
    Implement the host rollback workflow, its Redis/ToolsDB state, and the
    authenticated HTML/JSON surface.  They also expose framework-owned module
    registry, asset, configuration, job, and emergency-stop endpoints.

Supported module contract
-------------------------
A module supplies ``module.toml`` or ``module.json`` with a canonical name,
repository provenance URL, dotted Python entry point, and at least one UI,
cron-job, or worker-job surface.  Optional fields declare a blueprint, packaged
frontend resources/docs, module-local rights, Redis namespace, OAuth credential
*variable names*, and deployment buildpack metadata.  Buildpack declarations
are recorded in order; the registry does not download or run buildpacks.

Installed packages may advertise a definition through the
``chuck_buckbot.modules`` Python entry-point group.  Only definitions whose
names are allowlisted are persisted and enabled during normal startup.  A
rediscovered manifest updates code-owned metadata while preserving operator
enablement and mutable cron overrides.

Web blueprints execute in the host Flask process.  Job handlers execute through
``module_runner``; manually queued runs are supervised in child processes by
``module_job_controller`` for hard timeout and cancellation.  This process
boundary protects web availability from a stuck job, but neither path is a
security sandbox—module packages are trusted deployment dependencies.

Authorization and state ownership
---------------------------------
Framework rights use ``module:<name>:<right>`` atoms.  ``view`` and ``estop``
exist for every module; manifests may add rights referenced by sensitive jobs.
Maintainer and role-derived policy is evaluated before the legacy explicit
``module_access`` table, which remains supported for direct per-user grants.

Secrets stay in environment variables and manifests store only their names.
Operator-editable, non-secret settings live in ``module_config``.  ToolsDB is
authoritative for registry/run state, while Redis caches and progress records
are best-effort accelerators rather than lifecycle truth.
"""
