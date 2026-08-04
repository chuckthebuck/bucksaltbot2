# Buckbot Quickstart

This guide gets an isolated local Buckbot instance running for development and
review. It uses local Redis and MariaDB, enables the local login helper, and
forces framework-managed rollback/module-runner flows into dry run. It is not a
universal write barrier: File Changer's custom apply queue currently bypasses
`CHUCKBOT_LOCAL_SAFE_MODE`, so do not call that endpoint with live credentials.

## Prerequisites

- Python 3.11 or newer; every enabled external module requires at least 3.11
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
normal development, and use File Changer preview only. You do not need Wikimedia
OAuth credentials to build, inspect, or use dry-run flows locally.

Run the focused build and test canary:

```bash
bash scripts/canary-build.sh
```

The debug templates load assets from a real Vite server on port 5173. In one
terminal, start it explicitly:

```bash
npm exec vite -- --host 127.0.0.1
```

Then start the application processes in another terminal:

```bash
bash scripts/run-local-full.sh
```

The script starts Redis and MariaDB through Docker if they are not already
available, then runs Gunicorn, the shared Celery worker, the module job
controller, and the repository's historical `npm run dev` production-bundle
watcher. That watcher does **not** listen on port 5173, which is why the separate
`npm exec vite` process is currently required. Open
<http://127.0.0.1:5000>, then sign in through the local-only helper at
<http://127.0.0.1:5000/dev-login?user=chuckbot>.

Use `Ctrl-C` to stop the application processes. Stop the Docker-backed
services when you are finished:

```bash
bash scripts/local-services-down.sh
```

## Faster loops

For a web-only run with the Vite server already running, use:

```bash
bash scripts/canary-run-web.sh
```

To use built production assets instead, run `npm run build` and start the web
canary with `FLASK_DEBUG=0`.

This still requires Redis and MariaDB. Start or inspect them separately with:

```bash
bash scripts/canary-doctor.sh status
bash scripts/canary-doctor.sh up
```

For browser-connected frontend iteration and hot reload, run:

```bash
npm exec vite -- --host 127.0.0.1
```

`npm run dev` has a different, legacy meaning in this repository: it runs
`vite build --watch`, writes production assets, and does not start an HTTP
server.

## Everyday checks

Run the checks relevant to the files you changed:

```bash
# Python tests
.venv/bin/python -m pytest -q

# Frontend tests and static checks
npm run test
npm run lint
npm run typecheck

# Production frontend build
npm run build
```

`bash scripts/canary-build.sh` is the recommended pre-push framework check
because it also validates enabled modules, their manifests, the generated
frontend registry, and the Salt Shack registry. It runs focused integration
tests, not every module-owned suite under `vendor/modules/*/tests`; run the
changed module's tests separately.

## What to read next

- [Framework overview](../README.md) — architecture, permissions, APIs, and
  module contract.
- [Local canary reference](LOCAL_CANARY.md) — service-aware checks, editable
  modules, Docker Compose, and safety details.
- [Module development guide](MODULE_DEVELOPMENT_GUIDE.md) — build a module or
  add scheduled work.
- [Deployment documentation index](DEPLOYMENT_DOCS_INDEX.md) — deployment,
  versioning, and access-control references.
