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

- Python 3.11 (limited by celery's worker) 
- Node.js 22.x
- Redis
- MySQL / MariaDB
- A Wikimedia OAuth consumer key/secret (for user login)
- A Wikimedia bot account with OAuth credentials and the following grants (for executing edits)

    -Perform high volume activity

      -High-volume (bot) access
  
    -Interact with pages

       -Edit existing pages; Create, edit, and move pages; Patrol changes to pages
    -Perform administrative actions

      -Rollback changes to pages

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

## API Endpoints

All API endpoints are under the `/api/v1/` prefix and return JSON. Browser UI routes return HTML.

### Authentication

Requests to the JSON API must be authenticated via an active session cookie (obtained by logging in through the browser OAuth flow). The `POST /api/v1/rollback/jobs` endpoint additionally accepts an `X-Status-Token` header for machine-to-machine access (value must match the `STATUS_API_TOKEN` environment variable).

### Auth / UI Routes

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | — | Landing page |
| `GET` | `/login` | — | Initiates Wikimedia OAuth flow |
| `GET` | `/oauth-callback` | — | OAuth callback; completes login and stores session cookie |
| `GET` | `/logout` | Session | Clears session and redirects to `/` |
| `GET` | `/rollback-queue` | Session | Rollback queue page for the authenticated user |
| `GET` | `/rollback-queue/all-jobs` | Maintainer | Admin view of all jobs across all users |
| `GET` | `/rollback_batch` | Maintainer | Batch rollback submission page |
| `GET` | `/rollback-from-diff` | Maintainer | Rollback-from-diff submission page |
| `GET` | `/goto?tab=<tab>` | Session | Tab-based navigation redirect |

`/oauth-callback` is also registered at `/mas-oauth-callback`, `/mwoauth-callback`, and `/buckbot-oauth-callback` for backwards compatibility.

### JSON API

#### `GET /api/v1/rollback/worker`

Returns the Celery worker heartbeat status. No authentication required.

**Response**
```json
{ "status": "online", "last_seen": 4.2 }
// or
{ "status": "offline" }
```

---

#### `GET /api/v1/rollback/jobs`

Returns the authenticated user's active and recently-finished jobs (up to 100). Excludes completed jobs older than 2 hours and failed/canceled jobs older than 24 hours.

**Response**
```json
{
  "jobs": [
    {
      "id": 42,
      "requested_by": "ExampleUser",
      "status": "queued",
      "dry_run": false,
      "created_at": "2026-01-01 12:00:00"
    }
  ]
}
```

---

#### `POST /api/v1/rollback/jobs`

Creates one or more rollback jobs. Items are split into chunks of `MAX_JOB_ITEMS` (default 50), each becoming a separate job within the same batch.

**Request body (JSON)**
```json
{
  "items": [
    {
      "title": "File:Example.jpg",
      "user": "VandalUsername",
      "summary": "Optional edit summary"
    }
  ],
  "dry_run": false,
  "batch_id": 1234567890
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `items` | array | ✓ | List of rollback items (max 1000) |
| `items[].title` | string | ✓ | Full page title (e.g. `File:Example.jpg`) |
| `items[].user` | string | ✓ | Username whose edit will be rolled back |
| `items[].summary` | string | | Optional edit summary |
| `dry_run` | boolean | | If `true`, no edits are made (default: `false`) |
| `batch_id` | integer | | Group multiple jobs under one batch ID (auto-generated if omitted) |

**Response**
```json
{
  "job_id": 42,
  "job_ids": [42, 43],
  "chunks": 2,
  "batch_id": 1234567890,
  "status": "queued"
}
```

---

#### `GET /api/v1/rollback/jobs/<job_id>`

Returns full details of a job, including all its items. The job must belong to the authenticated user, or the user must be a maintainer.

Append `?format=log` to receive a plain-text log instead of JSON.

**Response**
```json
{
  "id": 42,
  "requested_by": "ExampleUser",
  "status": "completed",
  "dry_run": false,
  "created_at": "2026-01-01 12:00:00",
  "total": 2,
  "completed": 1,
  "failed": 1,
  "items": [
    {
      "id": 101,
      "title": "File:Example.jpg",
      "user": "VandalUsername",
      "summary": "Reverting vandalism",
      "status": "completed",
      "error": null
    }
  ]
}
```

---

#### `POST /api/v1/rollback/jobs/<job_id>/retry`

Re-queues a job (and all its items) that previously failed. Only the original requester may retry their own job.

**Response**
```json
{ "job_id": 42, "status": "queued" }
```

---

#### `DELETE /api/v1/rollback/jobs/<job_id>`

Cancels a queued or running job. Only the original requester may cancel their own job. Queued and running items are marked `canceled`; already-completed items are unaffected.

**Response**
```json
{ "job_id": 42, "status": "canceled" }
```

---

#### `POST /api/v1/rollback/from-diff`

*Maintainer only.* Resolves a diff revision URL or revision ID to a target user and timestamp, then automatically creates rollback jobs for all of that user's contributions made after that timestamp.

**Request body (JSON)**
```json
{
  "diff": "https://commons.wikimedia.org/w/index.php?diff=&oldid=987654321",
  "summary": "Reverting mass vandalism",
  "dry_run": false,
  "limit": 100
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `diff` | string | ✓ | Revision ID or diff URL containing `oldid` |
| `summary` | string | | Edit summary applied to all rolled-back edits |
| `dry_run` | boolean | | If `true`, no edits are made (default: `false`) |
| `limit` | integer | | Max contributions to roll back (1–10000) |

**Response**
```json
{
  "job_id": 42,
  "job_ids": [42],
  "chunks": 1,
  "batch_id": 1234567890,
  "total_items": 17,
  "status": "queued",
  "resolved_user": "VandalUsername",
  "resolved_timestamp": "2026-01-01T11:59:00Z",
  "oldid": 987654321,
  "diff": "987654321",
  "dry_run": false,
  "limit": 100
}
```

---

#### `GET /api/v1/rollback/jobs/progress?ids=1,2,3`

Returns live job progress for a comma-separated list of job IDs, read directly from Redis. Useful for polling the UI.

**Response**
```json
{
  "jobs": [
    { "id": 42, "total": 10, "completed": 7, "failed": 1, "status": "running" }
  ]
}
```

---

### Job and Item Status Values

| Status | Applies to | Description |
|---|---|---|
| `queued` | job, item | Waiting to be picked up by the worker |
| `running` | job, item | Currently being processed |
| `completed` | job, item | Successfully finished |
| `failed` | job, item | Processing encountered an error |
| `canceled` | job, item | Canceled by the requester before completion |

---

## Database Structure

The application uses a single MySQL/MariaDB database named `<db_user>__match_and_split`. The schema is initialised automatically by `toolsdb.py` on first connection.

### `rollback_jobs`

Represents a batch of rollback items submitted as a single job request.

| Column | Type | Description |
|---|---|---|
| `id` | `INT AUTO_INCREMENT` | Primary key |
| `requested_by` | `VARCHAR(255)` | Wikimedia username of the submitter |
| `status` | `VARCHAR(32)` | Job status (`queued`, `running`, `completed`, `failed`, `canceled`) |
| `dry_run` | `TINYINT(1)` | `1` if this is a dry run (no real edits made), `0` otherwise |
| `batch_id` | `BIGINT` | Groups multiple jobs created together (Unix epoch in milliseconds, auto-generated by the server or supplied by the caller) |
| `created_at` | `TIMESTAMP` | Row creation time (defaults to `CURRENT_TIMESTAMP`) |

### `rollback_job_items`

One row per individual page/file rollback within a job.

| Column | Type | Description |
|---|---|---|
| `id` | `INT AUTO_INCREMENT` | Primary key |
| `job_id` | `INT` | Foreign key → `rollback_jobs.id` (indexed) |
| `file_title` | `VARCHAR(512)` | Full page title of the file to roll back (e.g. `File:Example.jpg`) |
| `target_user` | `VARCHAR(255)` | Username of the editor whose edit is being reverted |
| `summary` | `TEXT` | Edit summary used when performing the rollback (nullable) |
| `status` | `VARCHAR(32)` | Item status (`queued`, `running`, `completed`, `failed`, `canceled`) |
| `error` | `TEXT` | Error message if the item failed or was canceled (nullable) |
| `created_at` | `TIMESTAMP` | Row creation time (defaults to `CURRENT_TIMESTAMP`) |

### Relationships

```
rollback_jobs (1) ──< rollback_job_items (many)
                        via rollback_job_items.job_id
```

Items are chunked at insert time: if more than `MAX_JOB_ITEMS` (default 50) items are submitted in one request, multiple `rollback_jobs` rows are created and linked under the same `batch_id`.

---

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
