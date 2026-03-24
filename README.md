# BuckSaltBot2

BuckSaltBot2 (tool name: **buckbot**) is a Wikimedia Commons administration tool that provides a web interface for submitting and processing automated rollback jobs. Authenticated Commons sysops and maintainers can queue rollback operations, which are then executed asynchronously by a background bot worker against Wikimedia Commons.

> **Built on [Match and Split](https://gitlab.wikimedia.org/toolforge-repos/matchandsplit/)** — BuckSaltBot2 uses the Celery task-queue infrastructure from the Match and Split tool as its foundation. The Celery worker architecture has been significantly overhauled and repurposed to drive rollback job processing rather than the original match/split functionality.

## Features

- **OAuth login** via Wikimedia account (sysops and registered maintainers only)
- **Rollback queue** — submit rollback jobs targeting a specific user's edits from a given timestamp
- **Batch rollback** — submit multiple rollback items at once
- **Rollback from diff** — derive rollback target from a diff/revision URL
- **Job monitoring** — track the status and progress of submitted jobs in real time
- **Admin view** — maintainers can see all queued jobs across all users

## Repository Structure

```
bucksaltbot2/
├── app.py                   # Flask app factory, Celery setup, maintainer auth
├── router.py                # All HTTP routes (login, API endpoints, UI pages)
├── blueprint.py             # Static asset blueprint
├── celery_worker.py         # Celery worker entry point
├── celery_init.py           # Celery initialization helper
├── rollback_queue.py        # Background task: processes rollback jobs via pywikibot
├── toolsdb.py               # MySQL connection management
├── redis_state.py           # Redis-backed job progress state
├── redis_init.py            # Redis client initialization
├── pywikibot_utils.py       # pywikibot helper utilities
├── editsummary.py           # Edit summary generation
├── utils.py                 # General utilities
├── cnf.py                   # Config file parser (.replica.my.cnf)
├── copy_file.py             # File copy utility
├── logger.py                # Logging configuration
├── user-config.tmpl         # pywikibot authentication template
│
├── client-src/              # Vue 3 + TypeScript frontend source
│   ├── App.vue              # Rollback queue UI
│   ├── AllJobsApp.vue       # Admin all-jobs view
│   ├── BatchApp.vue         # Batch rollback submission
│   ├── FromDiffApp.vue      # Rollback-from-diff submission
│   ├── api.ts               # API client (fetch wrappers)
│   ├── draft.ts             # Draft/form utilities
│   ├── script.ts            # Shared scripts
│   ├── styles.less          # Global styles
│   └── components/
│       ├── JobsTable.vue    # Jobs table component
│       └── JobItemRow.vue   # Individual job row component
│
├── templates/               # Jinja2 HTML templates
│   ├── base.html
│   ├── index.html
│   ├── rollback_queue.html
│   ├── rollback_queue_all_jobs.html
│   ├── batch_rollback.html
│   ├── rollback_from_diff.html
│   ├── status.html
│   ├── logs.html
│   └── all_status.html
│
├── tests/                   # Python test suite (pytest)
│   ├── conftest.py
│   ├── test_router.py
│   ├── test_blueprint.py
│   ├── test_rollback_queue.py
│   ├── test_toolsdb.py
│   └── test_utils.py
│
├── scripts/                 # Startup and deployment scripts
│   ├── run_dev_env.sh       # Start local dev environment
│   ├── start_gunicorn.sh    # Start production web server
│   ├── start_celery.sh      # Start Celery worker
│   ├── ping_celery.sh       # Celery health check
│   └── toolforge-deploy-new-version.sh
│
├── Dockerfile.web           # Docker image for the Flask web service
├── Dockerfile.celery        # Docker image for the Celery worker
├── docker-compose.yml       # Local Docker Compose configuration
├── Procfile                 # Process definitions for Toolforge
├── requirements.txt         # Python dependencies
├── package.json             # Node.js dependencies and build scripts
└── .python-version          # Pinned Python version (3.13)
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, Flask 3.x, Gunicorn |
| Task queue | Celery 5.x + Redis |
| Database | MySQL / MariaDB (via PyMySQL) |
| Bot API | pywikibot 11.x |
| Authentication | OAuth 1.0 via mwoauth |
| Frontend | Vue 3, TypeScript, Vite, Wikimedia Codex |
| Containerisation | Docker, Docker Compose |

## Prerequisites

- Python 3.13
- Node.js 22.x
- Redis
- MySQL / MariaDB
- A Wikimedia OAuth consumer key/secret (for user login)
- A Wikimedia bot account with OAuth credentials (for executing edits)

## Setup & Installation

### With Docker (recommended for local development)

Docker Compose automatically starts Redis, MariaDB, the Celery worker, and the Flask web server.

```bash
# Clone the repository
git clone https://github.com/chuckthebuck/bucksaltbot2.git
cd bucksaltbot2

# Start all services (foreground)
docker compose up

# Or start in detached (background) mode
docker compose up -d
```

> When using Docker, set `user = root` and `password = root` in `.replica.my.cnf` to match the MariaDB container credentials.

The tool will be available at **http://0.0.0.0:8000**.

To view logs from any container:

```bash
docker logs <container-name>   # e.g. docker logs web
```

### Without Docker

**1. Install system dependencies**

Ensure Python 3.13, Node.js 22.x, MySQL/MariaDB, and Redis are installed and running.

**2. Clone the repository**

```bash
git clone https://github.com/chuckthebuck/bucksaltbot2.git
cd bucksaltbot2
```

**3. Create and activate a Python virtual environment**

```bash
python3 -m venv venv
source venv/bin/activate
```

> See the [Python packaging guide](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/#create-and-use-virtual-environments) for more details.

**4. Install dependencies**

```bash
pip install -r requirements.txt
npm ci
```

**5. Configure the application**

Copy and fill in the required configuration files:

```bash
# Environment variables (OAuth keys, secret key, Celery URL, etc.)
cp .env.tmpl .env

# Database credentials
cp replica.my.cnf.tmpl .replica.my.cnf

# pywikibot bot authentication
cp user-config.tmpl user-config.py
```

See [Environment Variables](#environment-variables) below for a description of each setting.

**6. Start the development server**

```bash
./scripts/run_dev_env.sh
```

The tool will be available at **http://0.0.0.0:8000**.

### On Toolforge

Use Toolforge buildpacks and the checked-in `Procfile` instead of manually running `pip install`:

```bash
cd ..
./scripts/setup_all.sh --toolforge
```

This triggers `toolforge build start .` from the tool directory, then restarts the webservice and jobs.

#### Buildpack channel selection

The deploy script supports the `BUILDPACK_CHANNEL` environment variable:

```bash
# Use latest buildpack versions (default)
./scripts/toolforge-deploy-new-version.sh

# Test upcoming buildpack changes
BUILDPACK_CHANNEL=latest ./scripts/toolforge-deploy-new-version.sh

# Fall back temporarily while debugging
BUILDPACK_CHANNEL=deprecated ./scripts/toolforge-deploy-new-version.sh
```

#### Troubleshooting Toolforge builds

Warnings like the following are usually harmless and **not** the root cause of a failed build:

```text
warning: unsuccessful cred copy: ".docker" ... permission denied
```

A more meaningful error appears later in the logs, e.g.:

```text
ERROR: No buildpack groups passed detection.
```

When this happens, verify the build is started from the repository root (the directory containing `requirements.txt`, `package.json`, `package-lock.json`, and `Procfile`):

```bash
toolforge build start .
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `SECRET_KEY` | Flask session secret key | `dev-insecure-secret` |
| `USER_OAUTH_CONSUMER_KEY` | Wikimedia OAuth consumer key for user login | — |
| `USER_OAUTH_CONSUMER_SECRET` | Wikimedia OAuth consumer secret for user login | — |
| `CONSUMER_TOKEN` | Bot OAuth consumer token (pywikibot) | — |
| `CONSUMER_SECRET` | Bot OAuth consumer secret (pywikibot) | — |
| `ACCESS_TOKEN` | Bot OAuth access token (pywikibot) | — |
| `ACCESS_SECRET` | Bot OAuth access secret (pywikibot) | — |
| `CELERY_BROKER_URL` | Redis URL used as the Celery broker | `redis://redis.svc.tools.eqiad1.wikimedia.cloud:6379/9` |
| `CELERY_RESULT_BACKEND` | Redis URL used as the Celery result backend | same as `CELERY_BROKER_URL` |
| `BOT_ADMIN_ACCOUNTS` | Comma-separated list of extra admin usernames | — |
| `MAX_JOB_ITEMS` | Maximum number of items allowed per job | `50` |
| `FLASK_DEBUG` | Enable Flask debug mode (`1`/`0`) | `0` |
| `DOCKER` | Set to `TRUE` inside Docker containers | — |
| `NOTDEV` | If set, skips loading the `.env` file | — |

Database credentials are read from `.replica.my.cnf` (MySQL option file format).

## Running Tests

**Python (pytest):**

```bash
python -m pytest tests/
```

**Frontend (vitest):**

```bash
npm run test
```

**Type checking and linting:**

```bash
npm run typecheck
npm run lint
```

## Contributing

- Found a bug or have a feature request? Open a [ticket on Phabricator](https://phabricator.wikimedia.org/project/board/7238/).
- Code or documentation improvements are welcome as a Merge Request on the [GitLab repository](https://gitlab.wikimedia.org/toolforge-repos/matchandsplit/).
