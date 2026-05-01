# Chuck the Buckbot Framework Module Development Guide

Chuck the Buckbot Framework is a **module-first system**, allowing new modules to be developed, tested, and deployed independently while leveraging shared framework services. User-facing module names should follow the “Chuck the …” pattern, such as “Chuck the Rollback” or “Chuck the Four Award.”

## Quick Start

### 1. Define Your Module Manifest

Create `module.toml` in your module directory:

```toml
name = "example"
repo = "https://github.com/chuckthebuck/bucksaltbot2"
entry_point = "chuck_the_example.service:run"
ui = false
redis_namespace = "example"
title = "Chuck the Example"

[[jobs]]
name = "daily-sync"
run = "daily at 01:00"
handler = "chuck_the_example.service:run"
execution_mode = "k8s_job"
concurrency_policy = "forbid"
timeout_seconds = 300

# Option: Module with custom OAuth consumer
# oauth_consumer_mode = "module"
# oauth_consumer_key_env = "MY_MODULE_CONSUMER_KEY"
# oauth_consumer_secret_env = "MY_MODULE_CONSUMER_SECRET"
```

**Module Manifest Options:**
- `name` (required): Unique module identifier (alphanumeric, lowercase)
- `repo` (required): Git repository URL
- `entry_point` (required): Python import path to Flask blueprint
- `ui` (required if no cron): Boolean, enables Flask UI routes
- `jobs` / `cron_jobs` (required if no ui): List of scheduled job definitions
- `redis_namespace` (optional): Redis key prefix (defaults to module name)
- `title` (optional): Human-readable module name for admin UI
- `oauth_consumer_mode` (optional): `"default"` or `"module"` (default: `"default"`)
- `buildpacks` (optional): List of Heroku buildpack IDs for independent builds

### 2. Create Your Blueprint

Create `modules/my_module/blueprint.py`:

```python
from flask import Blueprint, render_template_string, session, abort

blueprint = Blueprint("my_module", __name__)

@blueprint.route("/")
def index():
    username = session.get("username")
    if not username:
        abort(401)
    
    return render_template_string("""
        <h1>My Module</h1>
        <p>Welcome, {{ username }}</p>
    """, username=username)

@blueprint.route("/api/v1/my_module/status")
def status():
    return {"status": "ok"}
```

### 3. Use Framework Services

Modules automatically have access to:

#### Authentication & Authorization
```python
from app import is_maintainer
from router.module_registry import user_has_module_access, get_module_definition

@blueprint.route("/protected")
def protected():
    username = session.get("username")
    if not user_has_module_access("my_module", username, is_maintainer=is_maintainer(username)):
        abort(403)
    return "Access granted"
```

#### Redis
```python
from redis_state import r as redis_client

redis_client.set("my_module:key", "value")
redis_client.get("my_module:key")
```

#### Database
```python
from toolsdb import get_conn

with get_conn() as conn:
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM my_table")
        rows = cursor.fetchall()
```

#### Logging
```python
from logger import Logger

logger = Logger("my_module")
logger.log("Something important happened")
```

#### Pywikibot
```python
from pywikibot_env import ensure_pywikibot_env
import pywikibot

ensure_pywikibot_env(strict=True)
site = pywikibot.Site("commons", "commons")
site.login()
```

#### Framework Context
```python
from router.module_runtime import build_module_context

context = build_module_context("my_module", username="Alice")
if context and context.has_access:
    print(f"Module namespace: {context.redis_namespace}")
```

### 4. Add Cron Jobs (Optional)

Define managed jobs in your manifest. Prefer `run` for human-readable schedules; raw cron remains available through `schedule` for advanced cases.

```toml
[[jobs]]
name = "hourly-refresh"
run = "every hour"
handler = "modules.my_module.service:run"
timeout_seconds = 600
enabled = true
```

Implement the handler:

```python
def run(ctx, payload):
    site = ctx.site("commons", "commons")
    # Implement your scheduled task here with full pywikibot access.
    return {"refreshed": True}
```

The framework will:
- Convert supported human schedules to cron
- Track queued/running/completed job runs
- Provide a control-plane API for run-now and cancel requests
- Launch scheduled runs through `python3 -m module_runner`
- Update `last_run_at` and `next_run_at` timestamps

#### Human-readable schedule syntax

Use the `run` field for schedules that should be readable without cron training.
The parser is intentionally small and deterministic; anything outside this list
should use raw cron in the `schedule` field instead.

Supported forms:

| Schedule text | Generated cron | Notes |
|---|---:|---|
| `every 15 minutes` | `*/15 * * * *` | Minute interval must be 1-59. |
| `every hour` | `0 * * * *` | Shortcut for hourly runs. |
| `every 6 hours` | `0 */6 * * *` | Hour interval must be 1-23. |
| `daily at 03:00` | `0 3 * * *` | Time is 24-hour `HH:MM`. |
| `weekly on monday at 09:30` | `30 9 * * 1` | Weekdays may be full names or 3-letter names. |
| `monthly on day 1 at 02:00` | `0 2 1 * *` | Day must be 1-31. |

Examples:

```toml
[[jobs]]
name = "quick-check"
run = "every 15 minutes"
handler = "chuck_the_example.service:run"
timeout_seconds = 300

[[jobs]]
name = "nightly-sync"
run = "daily at 03:00"
handler = "chuck_the_example.service:sync"
timeout_seconds = 900
```

Advanced users can bypass the human syntax with raw cron:

```toml
[[jobs]]
name = "weekday-report"
schedule = "15 8 * * 1-5"
handler = "chuck_the_example.service:report"
timeout_seconds = 300
```

### 5. Structure Your Module

```
chuck-the-example/
├── pyproject.toml
├── chuck_the_example/
│   ├── __init__.py
│   ├── manifest.py
│   └── service.py
└── README.md
```

Recommended package entry point:

```toml
[project.entry-points."chuck_buckbot.modules"]
example = "chuck_the_example.manifest:module_manifest"
```

Example `manifest.py`:

```python
def module_manifest():
    return {
        "name": "example",
        "repo": "https://github.com/chuckthebuck/chuck-the-example",
        "entry_point": "chuck_the_example.service:run",
        "redis_namespace": "example",
        "title": "Chuck the Example",
        "jobs": [
            {
                "name": "daily-sync",
                "run": "daily at 01:00",
                "handler": "chuck_the_example.service:run",
                "execution_mode": "k8s_job",
                "concurrency_policy": "forbid",
                "timeout_seconds": 300,
            }
        ],
    }
```

The framework automatically discovers installed packages that expose the
`chuck_buckbot.modules` entry point group. Bundled `modules/*/module.toml`
manifests still work for default modules like Chuck the Rollback.

### Installing Module Packages on Toolforge

Modules do not need to be published to PyPI or npm. Keep each module in its
own public Git repository and install it into the Buckbot buildservice image
with a direct Git dependency:

```txt
chuck-the-example @ git+https://github.com/chuckthebuck/chuck-the-example@main
```

For production, pin to a tag or commit instead of a moving branch:

```txt
chuck-the-example @ git+https://github.com/chuckthebuck/chuck-the-example@v2026.05.01
```

Put optional module dependencies in `requirements-modules.txt` and include
only the modules intended for the current deployment. The framework does not
clone module repositories at runtime; if a handler cannot be imported, the
module package was not installed into the image.

### 6. Access Control

Modules use a **binary access model**:
- **Maintainers** have access to all modules by default
- **Other users** need explicit grants via admin APIs or UI
- Admins can grant/revoke access in `/modules` web UI

Example:
```python
from app import is_maintainer
from router.module_registry import user_has_module_access

def check_access(username: str) -> bool:
    return user_has_module_access(
        "my_module",
        username,
        is_maintainer=is_maintainer(username)
    )
```

## Module Lifecycle

### Development
1. Create module files locally in `modules/my_module/`
2. Test with `ENABLE_MODULE_LOADING=1 pytest tests/`
3. Module blueprint must be importable and have a `blueprint` attribute

### Deployment
1. Commit module files to repository
2. On deploy, framework discovers `module.toml` files
3. Modules are bootstrapped from `modules/*/module.toml`
4. Blueprints auto-register under `/<module_name>/` paths
5. Admins can manage modules in `/modules` web UI

### Management
- **Enable/Disable**: Toggle in admin UI (no redeployment needed)
- **Grant Access**: Admin UI or API (`PUT /api/v1/modules/<module>/access`)
- **View Status**: Admin UI shows all modules and their endpoints

## API Reference

### Manifest (module.toml)

**Required:**
- `name`, `repo`, `entry_point`, and either `ui=true` or `cron_jobs` list

**Optional:**
- `redis_namespace`: Redis key prefix (auto-generated if omitted)
- `title`: Display name for admin UI
- `oauth_consumer_mode`: `"default"` or `"module"`
- `oauth_consumer_key_env`, `oauth_consumer_secret_env`: For module OAuth mode
- `buildpacks`: List of Heroku buildpack IDs

### Framework APIs

**Module Registry** (read-only in modules):
```python
from router.module_registry import get_module_definition, list_module_definitions

record = get_module_definition("my_module")
all_records = list_module_definitions(enabled_only=True)
```

**Access Control**:
```python
from router.module_registry import user_has_module_access

has_access = user_has_module_access(
    "my_module", 
    "alice", 
    is_maintainer=False
)
```

**Admin APIs** (`PUT /api/v1/modules/<module>/enabled`, etc.):
- GET `/api/v1/modules` — List all modules
- GET `/api/v1/modules/<module>` — Module details
- PUT `/api/v1/modules/<module>/enabled` — Toggle enable/disable
- PUT `/api/v1/modules/<module>/access` — Grant/revoke user access
- POST `/api/v1/modules/install` — Install a module from a GitHub or GitLab repository URL

## Toolforge Cron Jobs

On Toolforge, module cron jobs are managed via `jobs.yaml` instead of Celery Beat.

**Declaring scheduled jobs** in your module manifest:
```toml
[[jobs]]
name = "daily-sync"
run = "daily at 01:00"
handler = "chuck_the_example.service:run"
execution_mode = "k8s_job"
concurrency_policy = "forbid"
timeout_seconds = 300
enabled = true
```

**Implementing the handler** in your module:
```python
def run(ctx, payload):
    # Do work...
    return {"status": "ok"}
```

**Registering cron jobs** with Toolforge:
1. Install/update the module in the framework
2. As a maintainer, visit `/admin/jobs-yaml-preview` to generate entries
3. Copy the YAML section to `jobs.yaml` in the repo
4. Commit and push; Toolforge will redeploy with new cron schedules

## Best Practices

1. **Use unique namespace**: Prefix Redis keys with module name to avoid conflicts
   ```python
   redis_client.set(f"my_module:{key}", value)
   ```

2. **Document your endpoints**: Include docstrings and help text
   ```python
   @blueprint.route("/api/v1/my_module/status")
   def status():
       """Health check endpoint."""
       return {"status": "ok"}
   ```

3. **Handle errors gracefully**: Return appropriate HTTP status codes
   ```python
   try:
       result = do_work()
   except ValueError as e:
       return {"error": str(e)}, 400
   ```

4. **Test independently**: Write unit tests for module logic
   ```python
   def test_my_module_status(client):
       resp = client.get("/my_module/api/v1/status")
       assert resp.status_code == 200
   ```

5. **Use module context for initialization**: Access shared services
   ```python
   context = build_module_context("my_module", username="system")
   logger = context.logger
   namespace = context.redis_namespace
   ```

## Examples

See `modules/rollback/` for a complete bundled module example.

## Troubleshooting

**Module not loading?**
- Check `ENABLE_MODULE_LOADING=1` is set
- Verify `entry_point` exists and is importable
- Ensure blueprint has `.blueprint` attribute
- Check manifest is valid TOML

**Access denied?**
- User is not a maintainer
- User doesn't have explicit grant via admin UI
- Check `module_access` table for user grants

**Scheduled jobs not running?**
- Verify your module declares `jobs` in its manifest with `name`, `run`, and `handler`
- On Toolforge, cron jobs are defined in `jobs.yaml`; regenerate via the admin tool and update the repo
- Verify the handler package is installed and importable in the Build Service image
- Check `module_cron_jobs` table for job definitions and `enabled=1` flag
- Review `toolforge jobs logs <job-name>` for runner errors
