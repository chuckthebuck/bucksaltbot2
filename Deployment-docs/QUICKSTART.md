# Buckbot Quickstart

This guide gets a safe local Buckbot instance running for development and
review. It uses local Redis and MariaDB, enables the local login helper, and
blocks live wiki edits.

## Prerequisites

- Python 3.11 (or another `python3` that can create the project virtualenv)
- Node.js 22 (the supported range is `>=22.12.0 <23`)
- npm
- Docker Desktop with Docker Compose, unless you already run compatible local
  Redis and MariaDB services

Verify the command-line tools are available:

```bash
python3 --version
node --version
npm --version
docker compose version
```

## First local run

From the repository root, prepare the local configuration and install the
framework plus its enabled modules:

```bash
bash scripts/setup-local-env.sh
bash scripts/check-secrets.sh canary
bash scripts/install-framework.sh
bash scripts/install-modules.sh
```

`setup-local-env.sh` creates `.env` from `.env.example` when needed. The
checked-in local defaults set `CHUCKBOT_LOCAL_SAFE_MODE=1`; keep it enabled for
normal development. You do not need Wikimedia OAuth credentials to build,
inspect, or use dry-run flows locally.

Run the focused build and test canary:

```bash
bash scripts/canary-build.sh
```

Start the complete local stack:

```bash
bash scripts/run-local-full.sh
```

The script starts Redis and MariaDB through Docker if they are not already
available, then runs Vite, Gunicorn, the Celery worker, and the module job
controller. Open <http://127.0.0.1:5000>, then sign in through the local-only
helper at <http://127.0.0.1:5000/dev-login?user=chuckbot>.

Use `Ctrl-C` to stop the application processes. Stop the Docker-backed
services when you are finished:

```bash
bash scripts/local-services-down.sh
```

## Faster loops

For a web-only run, use:

```bash
bash scripts/canary-run-web.sh
```

This still requires Redis and MariaDB. Start or inspect them separately with:

```bash
bash scripts/canary-doctor.sh status
bash scripts/canary-doctor.sh up
```

For frontend-only iteration, Vite can watch and rebuild assets:

```bash
npm run dev
```

## Everyday checks

Run the checks relevant to the files you changed:

```bash
# Python tests
python3 -m pytest -q

# Frontend tests and static checks
npm run test
npm run lint
npm run typecheck

# Production frontend build
npm run build
```

`bash scripts/canary-build.sh` is the recommended pre-push check because it
also validates enabled modules, their manifests, generated frontend registry,
and Salt Shack registry.

## What to read next

- [Framework overview](../README.md) — architecture, permissions, APIs, and
  module contract.
- [Local canary reference](LOCAL_CANARY.md) — service-aware checks, editable
  modules, Docker Compose, and safety details.
- [Module development guide](MODULE_DEVELOPMENT_GUIDE.md) — build a module or
  add scheduled work.
- [Deployment documentation index](DEPLOYMENT_DOCS_INDEX.md) — deployment,
  versioning, and access-control references.
