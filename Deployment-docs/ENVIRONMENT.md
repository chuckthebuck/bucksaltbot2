# Environment and Secrets

Environment variables are for credentials, service connections, deployment
identity, and boot-time safety controls. Operational settings that maintainers
change without restarting the service belong in framework/module runtime
configuration instead.

Local development reads `.env` through the repository scripts. Production
values belong in Toolforge's envvars service; never commit live values to Git,
`jobs.yaml`, or a module manifest.

Check presence without printing values:

```bash
bash scripts/check-secrets.sh canary
bash scripts/check-secrets.sh live
```

## Live secrets

| Name | Purpose |
| --- | --- |
| `SECRET_KEY` | Flask session signing. The development fallback is not acceptable for production. |
| `USER_OAUTH_CONSUMER_KEY` | OAuth consumer key for user login. |
| `USER_OAUTH_CONSUMER_SECRET` | OAuth consumer secret for user login. |
| `CONSUMER_TOKEN` | Pywikibot consumer token for bot-owned wiki actions. |
| `CONSUMER_SECRET` | Pywikibot consumer secret for bot-owned wiki actions. |
| `ACCESS_TOKEN` | Pywikibot access token for bot-owned wiki actions. |
| `ACCESS_SECRET` | Pywikibot access secret for bot-owned wiki actions. |
| `STATUS_API_TOKEN` | Optional shared token for the separate status-site machine identity. |
| `MODULE_CRON_TOKEN` | Required only by legacy `execution_mode = "http"` jobs. Handler jobs do not use it. |

`FALLBACK_SECRET_KEY` is a compatibility fallback read by the router. Configure
`SECRET_KEY` instead.

## Deployment identity and login

| Name | Default/behavior |
| --- | --- |
| `BOT_NAME` | Tool identity and default Toolforge callback hostname; falls back to `TOOL_NAME`, then `buckbot`. |
| `TOOL_NAME` | Compatibility/fallback tool identity. |
| `BOT_ADMIN_ACCOUNTS` | Comma-separated emergency/local bot-admin usernames. Toolhub maintainers are also recognized. |
| `CONFIG_EDIT_PRIMARY_ACCOUNT` | Bot admin allowed to replace the protected authz document; defaults to `chuckbot`. |
| `USER_OAUTH_CALLBACK_URL` | Explicit OAuth callback override; otherwise `https://<BOT_NAME>.toolforge.org/mas-oauth-callback`. |
| `WIKI_API_URL` | Framework Wikimedia API used for default group/account lookups; defaults to Commons. |
| `MWOAUTH_BASE_URL` / `MWOAUTH_INDEX_URL` | OAuth provider overrides; normally keep the Meta-Wiki defaults. |
| `ALLOWED_GROUPS` | Compatibility login/group baseline; defaults to `sysop,rollbacker`. |
| `BOT_DOCS_URL` | Header documentation link; defaults to `/docs`. |
| `UNAUTHORIZED_MESSAGE` | Optional replacement for the normal unauthorized message. |

The current authz policy keys are `ROLLBACK_CONTROL_JSON`, `ROLE_GRANTS_JSON`,
`CHUCKBOT_GROUPS_JSON`, `CHUCKBOT_GROUP_DESCRIPTIONS_JSON`, and the two rate
limits. Their production values should be saved in `runtime_config` through the
protected config UI/API. Environment values provide startup/default and legacy
compatibility input; see [ACCESS_CONTROL.md](ACCESS_CONTROL.md) before changing
them.

## Module bootstrap and execution

| Name | Default/behavior |
| --- | --- |
| `ENABLE_MODULE_LOADING` | Defaults to `1`. Set exactly `0` to suppress registry/Blueprint bootstrap, then restart processes. |
| `ENABLED_MODULES` | Optional comma-separated additions to `enabled-modules.txt`; it does not remove names from the file. |
| `NOTDEV` | Production-mode marker. Toolforge scripts set it to `1`. |
| `MAX_JOB_ITEMS` | Rollback batch chunk size; defaults to `500`. |
| `RESOLVING_TIMEOUT_SECONDS` | Time before an abandoned resolving rollback request is failed; defaults to `1800`. |
| `MODULE_JOB_CONTROLLER_POLL_SECONDS` | Cancellation/timeout poll interval while supervising an active child process; bounded to 0.1–5 seconds and defaults to `0.5`. |
| `MODULE_JOB_CONTROLLER_SLEEP` | Delay after an idle controller pass; defaults to `15`. |
| `MODULE_ESTOP_DISABLE_TOOLFORGE_KILL` | `1`, `true`, or `yes` suppresses the Toolforge job/pod deletion attempt during module E-STOP. Cancellation rows are still requested. |
| `MODULE_CRON_BASE_URL` | Base URL used only for compatibility HTTP cron commands. |

`ENABLE_MODULE_LOADING=0` does not erase registry state or uninstall packages.
It is a process bootstrap switch, not a persistent per-module disable.

## Redis and Celery

| Name | Default/behavior |
| --- | --- |
| `TOOL_REDIS_URI` | Redis connection used for framework status/progress state. Toolforge uses its shared Redis service by default. |
| `CELERY_BROKER_URL` | Celery broker URL. Defaults to Toolforge Redis database 9. |
| `CELERY_RESULT_BACKEND` | Celery result backend; defaults to the broker URL. |
| `BUCKBOT_REDIS_NAMESPACE` | Prefix isolating framework, Kombu, and result keys; defaults to `buckbot`. |
| `BUCKBOT_CELERY_QUEUE` | The single queue Buckbot sends to and consumes; defaults to `<namespace>.celery`. |
| `BUCKBOT_CELERY_WORKER_NAME` | Worker hostname prefix; defaults to `<namespace>-celery`. |
| `REDIS_KEY_PREFIX` | Compatibility override for framework state keys; normally leave unset so it follows `BUCKBOT_REDIS_NAMESPACE`. |

The webservice, Celery worker, controller, and administrative shell must use the
same namespace and queue. Every staging tool or fork sharing Redis needs a
different namespace. Do not point two independent deployments at the same
namespace unless they intentionally share work.

Changing namespaces does not move or delete messages already on the previous
queue. Drain the old Buckbot queue first, or deliberately discard it only after
confirming no other deployment uses it.

## ToolsDB and filesystem

ToolsDB credentials are resolved in this order:

1. `~/replica.my.cnf`;
2. `$TOOL_DATA_DIR/replica.my.cnf`; then
3. `TOOL_TOOLSDB_USER` and `TOOL_TOOLSDB_PASSWORD` environment fallbacks.

A CNF file is authoritative for user/password. `TOOL_TOOLSDB_HOST` can override
the host, and `TOOL_TOOLSDB_DATABASE` can select an explicit database. Without
an explicit database the framework retains its historical
`<db-user>__match_and_split` name.

| Name | Purpose |
| --- | --- |
| `TOOL_DATA_DIR` | Persistent runtime data/log root; a Toolforge deployment normally uses `/data/project/<tool-name>`. |
| `PYWIKIBOT_DIR` | Pywikibot configuration directory. |
| `TOOLFORGE` | Optional explicit Toolforge-detection marker. Normal tool-home and ToolsDB credentials also trigger detection. |
| `PORT` | Gunicorn listen port assigned by Build Service; defaults to `8000` in the start script. |

## Safety, diagnostics, and status

| Name | Purpose |
| --- | --- |
| `CHUCKBOT_LOCAL_SAFE_MODE` | Local-only guard for rollback and `module_runner`-managed mutation paths. It does not currently protect File Changer's custom apply queue; never use it as a universal or production authorization barrier. |
| `FLASK_DEBUG` | Enables the local debug asset behavior; keep `0`/unset in production. |
| `VITE_ORIGIN` | Local Vite asset origin; defaults to `http://localhost:5173`. |
| `BUCKBOT_STARTUP_SELFTEST` | Run `framework_selftest` during application import when set to `1`. |
| `BUCKBOT_STARTUP_SELFTEST_SERVICES` | Include Redis/ToolsDB checks in that startup self-test when set to `1`. |
| `BUCKBOT_STARTUP_SELFTEST_STRICT` | Fail startup when the enabled self-test fails; defaults to `1`. |
| `STATUS_UPDATE_MIN_INTERVAL_SECONDS` | Minimum interval between equivalent status writes. Production `jobs.yaml` defaults this to `86400`. |
| `STATUS_CRON_EDITING` / `STATUS_CRON_WEB` / `STATUS_CRON_DETAILS` | Text written by the status cron. |
| `STATUS_API_USER` | Username assigned to valid `STATUS_API_TOKEN` requests; defaults to `status-site`. |

Variables beginning `LIVE_TEST_` are integration-test controls, not production
configuration. `.env.example` sets
`LIVE_TEST_DISABLE_STATUS_UPDATES=1` so a local canary cannot update the wiki
status page.

## HTTP identity and module-specific values

`BUCKBOT_HTTP_USER_AGENT` replaces the framework's full versioned Wikimedia
User-Agent. Leave it blank to use the checked framework version. Modules own
their identities independently; the current snapshots read
`FOUR_AWARD_HTTP_USER_AGENT` and `CHUCK_FILE_CHANGER_USER_AGENT`.

4Award also reads `FOUR_AWARD_*` environment defaults, but framework runtime
module config overrides those values at the start of a managed run. Prefer the
module config UI for non-secret behavior flags. A module manifest that uses a
separate OAuth consumer declares only the names of its four credential
variables; the corresponding secret values still belong in Toolforge envvars.
