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
bash scripts/local-services-up.sh
bash scripts/run-local-full.sh
```

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

The app detects Toolforge by the real Toolforge DB config path
`~/replica.my.cnf`, `TOOL_DATA_DIR/replica.my.cnf`, or the
`TOOL_TOOLSDB_USER` / `TOOL_TOOLSDB_PASSWORD` environment variables. On
Toolforge the default DB host is `tools.db.svc.wikimedia.cloud`. In local safe
mode, local env vars such as `TOOL_TOOLSDB_HOST`, `TOOL_TOOLSDB_USER`,
`TOOL_TOOLSDB_PASSWORD`, and `TOOL_TOOLSDB_DATABASE` control the database
connection.
