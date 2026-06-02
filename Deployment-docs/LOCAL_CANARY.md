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
python -m pip install -e ../module4awardhelper
python scripts/check-module-install.py
```

The editable install provides the same package entry point as the vendored
snapshot, so `enabled-modules.txt` does not change. Restart the local web or job
process after Python changes if it has already imported the module.

If the module frontend changed, build it in the module repo:

```bash
cd ../module4awardhelper
npm install
npm run build
```

Only refresh `vendor/modules/<module_name>/` when preparing a framework commit
that should deploy or be reviewed as a pinned bundle.

For 4Award framework-integration work, it is also acceptable to edit the
vendored copy first and backport the subtree after review:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
```

Use the matching VS Code preview task before pushing the split to the 4Award
repo. The helper refuses splits that accidentally include framework files.

## Canary Check

```bash
bash scripts/canary-build.sh
```

The default canary checks:

- Python dependencies are installed in `.venv`.
- Enabled modules have either local manifests or installed package entry points.
- `module-frontend-packages.json` generates `client-src/moduleRegistry.generated.ts`.
- The production Vite build succeeds.
- Focused module/registry/jobs-yaml tests pass.

To run the larger local test suite after the focused canary:

```bash
CANARY_FULL_TESTS=1 bash scripts/canary-build.sh
```

That still ignores `tests/live`. It may require local Redis/MySQL depending on
which tests touch app routes.

## Run Web Canary

For a full MacBook rehearsal without live wiki edits:

```bash
bash scripts/run-local-full.sh
```

`run-local-full.sh` prepares `.env`, creates local data directories, starts
Docker Redis/MariaDB if they are not already reachable, and then starts the app
processes.

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

This runs:

- Redis and MariaDB in Docker.
- Vite dev assets.
- Flask/Gunicorn locally from `.venv`.
- Celery rollback worker locally from `.venv`.
- Module job controller locally from `.venv`.

For just the web process:

```bash
bash scripts/canary-run-web.sh
```

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

Stop local services when done:

```bash
bash scripts/local-services-down.sh
```

## Docker Compose Path

The compose stack uses the same local-safe defaults and a local MariaDB database
named `chuckbot_local`.

```bash
docker-compose build
docker-compose up
```

or, on newer Docker installs:

```bash
docker compose build
docker compose up
```

Open:

```txt
http://127.0.0.1:8000/dev-login?user=chuckbot
```

The canary scripts load `.env` and then apply local Docker defaults. From the
host-run canary scripts, MariaDB is expected on `127.0.0.1:3306` after
`scripts/local-services-up.sh` starts the Docker service. Inside Docker Compose,
the DB host is `mariadb`.

Ad-hoc Python imports do not start canary services. For module manifest checks
that should not need a DB, use:

```bash
python3 scripts/check-module-manifest.py vendor/modules/chuck_file_changer/modules/chuck_file_changer/module.toml
```

Runtime DB config still comes from `~/replica.my.cnf`,
`TOOL_DATA_DIR/replica.my.cnf`, or local env vars such as `TOOL_TOOLSDB_HOST`,
`TOOL_TOOLSDB_USER`, `TOOL_TOOLSDB_PASSWORD`, and `TOOL_TOOLSDB_DATABASE`.
