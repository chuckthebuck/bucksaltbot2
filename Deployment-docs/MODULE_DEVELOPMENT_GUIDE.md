# Module Development Guide

The Buckbot framework is built as a **module-first system**, allowing new modules to be developed, tested, and deployed independently while leveraging shared framework services.

## Quick Start

### 1. Define Your Module Manifest

Create `module.toml` in your module directory:

```toml
name = "my_module"
repo = "https://github.com/chuckthebuck/bucksaltbot2"
entry_point = "modules.my_module.blueprint"
ui = true
redis_namespace = "my_module"
title = "My Module"

# Option A: UI-only module (no cron)
# (already configured above)

# Option B: Cron-only module (example)
# [[cron_jobs]]
# name = "daily-sync"
# schedule = "0 1 * * *"
# endpoint = "/api/v1/my_module/cron/sync"
# timeout_seconds = 300

# Option C: Module with custom OAuth consumer
# oauth_consumer_mode = "module"
# oauth_consumer_key_env = "MY_MODULE_CONSUMER_KEY"
# oauth_consumer_secret_env = "MY_MODULE_CONSUMER_SECRET"
```

**Module Manifest Options:**
- `name` (required): Unique module identifier (alphanumeric, lowercase)
- `repo` (required): Git repository URL
- `entry_point` (required): Python import path to Flask blueprint
- `ui` (required if no cron): Boolean, enables Flask UI routes
- `cron_jobs` (required if no ui): List of scheduled job definitions
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

Define cron jobs in your manifest:

```toml
[[cron_jobs]]
name = "hourly-refresh"
schedule = "0 * * * *"
endpoint = "/api/v1/my_module/cron/refresh"
timeout_seconds = 600
enabled = true
```

Implement the endpoint:

```python
@blueprint.route("/api/v1/my_module/cron/refresh")
def cron_refresh():
    # Framework checks credentials before calling
    # Implement your scheduled task here
    return {"refreshed": True}
```

The framework will:
- Calculate next run times based on cron expression
- Invoke endpoints automatically on schedule
- Update `last_run_at` and `next_run_at` timestamps
- Retry on failure with exponential backoff

### 5. Structure Your Module

```
modules/my_module/
├── __init__.py                 # Package marker
├── module.toml                 # Manifest (required)
├── blueprint.py                # Flask Blueprint entry point (required)
├── handlers.py                 # Business logic (optional)
└── requirements.txt            # Module-specific deps (optional)
```

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

**Cron jobs not running?**
- Verify Celery Beat is running
- Check `module_cron_jobs` table for job definitions
- Review logs for endpoint invocation errors
- Confirm `enabled=1` for the job
