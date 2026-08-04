# Local Canary Build

Use this before pushing a framework deploy commit to Toolforge.

## First-Time Setup

```bash
bash scripts/setup-local-env.sh
bash scripts/check-secrets.sh canary
bash scripts/install-framework.sh
bash scripts/install-modules.sh
```

`setup-local-env.sh` creates `.env` from `.env.example` and creates local data
directories. Edit `.env` only for local secrets or local Redis/MySQL endpoints.

## Module Pins

Python module snapshots are vendored in:

```txt
vendor/modules/<module_name>/
```

and installed from:

```txt
requirements-modules.txt
```

Example:

```txt
./vendor/modules/four_award
```

Enabled module manifest names are listed in:

```txt
enabled-modules.txt
```

Example:

```txt
rollback
four_award
```

Optional Node/Vue module imports are listed in:

```txt
module-frontend-packages.json
```

The frontend registry is generated at build time. It is not runtime module
loading.

## Editable Module Development

For active module work, the cleanest path is to clone the module repo next to
the framework repo and install it editable into the framework virtualenv:

```bash
.venv/bin/python -m pip install -e ../module4awardhelper
.venv/bin/python scripts/check-module-install.py
```

The editable install provides the same package entry point as the vendored
snapshot, so `enabled-modules.txt` does not change. Restart the local web or job
process after Python changes if it has already imported the module.

Frontend iteration depends on the manifest mode. For `bundled = false`, build
the sibling module's packaged static assets. For `bundled = true`, the root
Vite build follows `module-frontend-packages.json`; its current 4Award and File
Changer imports point into `vendor/`, not an editable sibling. Refresh the
vendored snapshot or use a temporary sibling-source registry import for local
iteration, then run `npm run build`. Do not commit a developer-specific path.

Refresh `vendor/modules/<module_name>/` when preparing a framework commit that
should deploy or be reviewed as a pinned bundle.

For 4Award framework-integration work, it is also acceptable to edit the
vendored copy first and backport the subtree after review:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
```

Use the matching VS Code preview task before pushing the split to the 4Award
repo. The helper refuses splits that accidentally include framework files.

For normal inbound updates of all deploy snapshots, use
`npm run modules:update` from a clean framework worktree. That command performs
a clone-and-overlay refresh; `git subtree pull` is not the supported inbound
workflow.

## Canary Check

```bash
bash scripts/canary-build.sh
```

The default canary checks:

- `.venv/bin/python -m framework_selftest` passes without requiring Redis, ToolsDB, or
  Toolforge.
- Python dependencies are installed in `.venv`.
- Enabled modules have local or vendored manifests.
- Enabled module handler modules are resolvable from installed or vendored
  source.
- Enabled module frontend assets and docs exist.
- `module-frontend-packages.json` generates `client-src/moduleRegistry.generated.ts`.
- The production Vite build succeeds.
- Focused module/registry/jobs-yaml tests pass.

It does **not** run every module-owned suite under `vendor/modules/*/tests`.
Run the changed module's Python and frontend tests from that module root before
accepting a vendored refresh.

To run the larger local test suite after the focused canary:

```bash
CANARY_FULL_TESTS=1 bash scripts/canary-build.sh
```

That still ignores `tests/live`. It may require local Redis/MySQL depending on
which tests touch app routes.

For a service-aware self-test after local Redis/MariaDB are running:

```bash
.venv/bin/python -m framework_selftest --services
```

On Toolforge, startup self-test is opt-in:

```bash
BUCKBOT_STARTUP_SELFTEST=1
BUCKBOT_STARTUP_SELFTEST_SERVICES=1
BUCKBOT_STARTUP_SELFTEST_STRICT=1
```

Leave `BUCKBOT_STARTUP_SELFTEST_SERVICES=0` for a static/package startup check
that does not touch Redis or ToolsDB.

## Run Web Canary

First start the actual Vite development server in its own terminal:

```bash
npm exec vite -- --host 127.0.0.1
```

Then, in another terminal, start the application side of a full MacBook
rehearsal:

```bash
bash scripts/run-local-full.sh
```

`run-local-full.sh` prepares `.env`, creates local data directories, starts
Docker Redis/MariaDB if they are not already reachable, and then starts the app
processes. Its internal `npm run dev` command is a production-bundle watcher,
not the port-5173 server expected by debug templates, so the explicit Vite
process above is currently required.

On macOS, if Docker is installed but the daemon is not running, the canary
helpers try to open Docker Desktop and wait for it. Set
`CANARY_START_DOCKER_DESKTOP=0` to disable that behavior.

Open:

```txt
http://127.0.0.1:5000
```

Then use the local-only login shim:

```txt
http://127.0.0.1:5000/dev-login?user=chuckbot
```

`/dev-login` returns `404` unless `CHUCKBOT_LOCAL_SAFE_MODE=1`.

Together these commands run:

- Redis and MariaDB in Docker.
- A real Vite dev server plus the script's legacy production-bundle watcher.
- Flask/Gunicorn locally from `.venv`.
- Shared Rollback/module Celery worker locally from `.venv`.
- Module job controller locally from `.venv`.

For just the web process, first keep the explicit Vite server running and use:

```bash
bash scripts/canary-run-web.sh
```

Alternatively, run `npm run build` and invoke
`FLASK_DEBUG=0 bash scripts/canary-run-web.sh` to use the checked production
manifest without port 5173.

For a quick local service check:

```bash
bash scripts/canary-doctor.sh status
bash scripts/canary-doctor.sh up
```

`.env.example` sets `CHUCKBOT_LOCAL_SAFE_MODE=1`. In that mode:

- Rollback API requests are forced to `dry_run=true`.
- The “run live” endpoint returns `403`.
- Rollback worker authenticated wiki editing is blocked.
- Module job config receives `dry_run=true` and
  `publish_dry_run_report=false`.
- Status updater wiki writes are disabled by
  `LIVE_TEST_DISABLE_STATUS_UPDATES=1`.

This is not a universal module write barrier. File Changer's custom apply
Blueprint dispatches its own Celery/table queue without a `module_runner`
context, so it does not currently receive the safe-mode override. Use File
Changer preview only in a local stack and never supply live credentials while
testing that apply path.

Stop local services when done:

```bash
bash scripts/local-services-down.sh
```

## Docker Compose Boundary

Use Compose as the supported Redis/MariaDB infrastructure path:

```bash
docker compose up -d redis mariadb
```

The checked full Compose application is not currently equivalent to
`run-local-full.sh`: its web service inherits the same missing port-5173 Vite
server, and the file declares no `module_job_controller` service. Starting all
Compose services therefore leaves generic manual/Four Award runs queued and the
debug UI without assets. Use the host-run application commands above until the
Compose definition grows those processes.

The canary scripts load `.env` and then apply local Docker defaults. From the
host-run canary scripts, MariaDB is expected on `127.0.0.1:3306` after
`scripts/local-services-up.sh` starts the Docker service. Inside Docker Compose,
the DB host is `mariadb`.

Ad-hoc Python imports do not start canary services. For module manifest checks
that should not need a DB, use:

```bash
.venv/bin/python scripts/check-module-manifest.py vendor/modules/chuck_file_changer/modules/chuck_file_changer/module.toml
```

Runtime DB config still comes from `~/replica.my.cnf`,
`TOOL_DATA_DIR/replica.my.cnf`, or local env vars such as `TOOL_TOOLSDB_HOST`,
`TOOL_TOOLSDB_USER`, `TOOL_TOOLSDB_PASSWORD`, and `TOOL_TOOLSDB_DATABASE`.
