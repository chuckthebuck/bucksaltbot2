# Module Framework Deployment Prep

This document guides you through preparing the Buckbot module framework for production deployment.

## Pre-Deployment Checklist

### 1. Framework Configuration

- [ ] **Enable module loading** in production environment:
  ```bash
  export ENABLE_MODULE_LOADING=1
  ```
  
- [ ] **Verify Celery Beat is configured** for cron jobs:
  - Beat scheduler must be running alongside worker
  - Check `app.py` beat_schedule configuration
  - Cron jobs will check every 60 seconds for due jobs

- [ ] **Confirm module cron endpoints are accessible** internally:
  - Set `MODULE_CRON_BASE_URL` if using non-standard port
  - Default: `http://localhost:5000`

### 2. Database Schema

- [ ] **Module tables auto-created on startup**:
  ```
  module_registry — Module definitions and enabled state
  module_cron_jobs — Scheduled cron job metadata
  module_access — User access grants (non-maintainer)
  ```

- [ ] **Initialize cron job next_run_at timestamps** (one-time on first deploy):
  ```bash
  celery -A celery_worker call module_cron_executor.initialize_module_cron_next_run_times
  ```

### 3. Bundled Modules

- [ ] **Rollback module** (`modules/rollback/`):
  - [x] Manifest exists and is valid
  - [x] Blueprint entry point is correctly specified
  - [x] Uses framework's Python 3.11 buildpacks
  - [x] Provides UI and redirects to legacy routes
  - [ ] Test locally: `curl http://localhost:5000/rollback/`

### 4. Testing

- [ ] **Run full test suite**:
  ```bash
  pytest tests/ -v
  ```
  
  All should pass, including:
  - Module registry tests (manifest parsing, DB persistence)
  - Module runtime tests (blueprint registration)
  - Module cron executor tests (schedule calculation, endpoint invocation)
  - Rollback module integration tests
  - Router API tests (module management endpoints)

- [ ] **Test module bootstrap**:
  ```bash
  ENABLE_MODULE_LOADING=1 python -c "from app import flask_app; print([m for m in flask_app.blueprints if 'module' in m])"
  ```
  Should show: `['rollback_module', ...]`

- [ ] **Test module admin UI** (local or staging):
  - Navigate to `/modules` (maintainer-only)
  - Verify module list loads
  - Test enable/disable toggle
  - Test user access grant form

- [ ] **Test cron executor** (if using cron jobs in any module):
  ```bash
  celery -A celery_worker call module_cron_executor.run_overdue_module_cron_jobs
  ```
  Should return success with execution summary

### 5. Dependencies

- [ ] **New Python packages installed**:
  - `croniter` — Cron schedule calculation
  
  Verify: `pip show croniter`

- [ ] **Existing packages versions stable**:
  - Flask, Celery, Redis, PyMySQL unchanged
  - All in `requirements.txt`

### 6. Vue Admin Interface

- [ ] **Module management tab visible** to maintainers:
  - Header nav includes "Modules" tab
  - Clicking goes to `/goto?tab=modules`
  - Page loads module list from API

- [ ] **API endpoints respond**:
  ```bash
  curl -H "Cookie: session=..." http://localhost:5000/api/v1/modules
  curl -H "Cookie: session=..." http://localhost:5000/api/v1/modules/rollback
  ```

### 7. Environment Variables

Required for production:

```bash
export ENABLE_MODULE_LOADING=1
export MODULE_CRON_BASE_URL=http://localhost:5000  # or your service URL
export TOOL_DATA_DIR=/data/project/buckbot          # Toolforge standard
export NOTDEV=1                                     # Production flag
```

Optional:

```bash
export CELERY_BROKER_URL=redis://broker:6379/9
export CELERY_RESULT_BACKEND=redis://broker:6379/9
```

### 8. Deployment Steps

1. **Pull code** and run migrations:
   ```bash
   git pull origin main
   ```

2. **Install/upgrade dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Start services**:
   ```bash
   # Web service
   gunicorn -w 4 -b 0.0.0.0:5000 'app:flask_app'
   
   # Celery worker
   celery -A celery_worker worker -l info
   
   # Celery Beat scheduler (for cron jobs)
   celery -A celery_worker beat -l info
   ```

4. **Initialize cron timestamps** (one-time):
   ```bash
   celery -A celery_worker call module_cron_executor.initialize_module_cron_next_run_times
   ```

5. **Verify bootstrap**:
   ```bash
   curl http://localhost:5000/api/v1/modules
   ```
   Should list all bundled modules (rollback, etc.)

6. **Check logs**:
   - Web service: Should show module registration on startup
   - Worker: Should show cron executor running every 60s
   - Beat: Should log task scheduling

7. **Install external modules**:
   - Use `POST /api/v1/modules/install` with a GitHub or GitLab repo URL to add a module without bundling it in the framework repo.

### 9. Rollback Plan

If issues occur:

1. **Disable modules** without redeploying:
   ```bash
   export ENABLE_MODULE_LOADING=0
   # Restart web service
   ```
   
2. **Disable specific module**:
   - Toggle in `/modules` admin UI, or
   - API: `PUT /api/v1/modules/rollback/enabled {"enabled": false}`
   
3. **Clear module access grants**:
   ```sql
   DELETE FROM module_access WHERE module_name='rollback';
   ```

4. **Revert to previous version** (if major issues):
   ```bash
   git revert HEAD
   git push
   # Restart services
   ```

## Post-Deployment Verification

After deploying, run these checks:

### Health Checks

```bash
# Web service responsive
curl -I http://localhost:5000/

# Module registry loaded
curl http://localhost:5000/api/v1/modules | jq '.modules | length'

# Rollback module accessible
curl -b "session=<cookie>" http://localhost:5000/rollback/ | grep -q "Rollback"

# Cron executor task defined
celery -A celery_worker inspect active_queues | grep module_cron_executor
```

### Database Checks

```bash
# Module tables exist
SELECT COUNT(*) FROM module_registry;
SELECT COUNT(*) FROM module_cron_jobs;
SELECT COUNT(*) FROM module_access;

# Rollback module registered
SELECT * FROM module_registry WHERE name='rollback';

# Cron jobs populated
SELECT * FROM module_cron_jobs;
```

### Admin UI Checks

1. Log in as maintainer
2. Navigate to `/modules`
3. Verify:
   - Module list loads
   - "Rollback" module shows as enabled
   - Can toggle enable/disable
   - Can grant user access
   - Page doesn't show errors

### Cron Job Checks (if applicable)

1. Wait 60+ seconds
2. Check Celery Beat logs for task execution
3. Verify module endpoint was called:
   ```bash
   tail -f logs/module_cron_executor.log | grep "Invoking"
   ```

## Monitoring

Add alerts for:

1. **Module registry failures**:
   - Monitor `module_cron_executor` task failures
   - Alert on repeated failures (>3 in 5 minutes)

2. **Cron job lateness**:
   - Compare `next_run_at` with current time
   - Alert if jobs fall >5 minutes behind

3. **Module access errors**:
   - Monitor 403 responses to module routes
   - Log who's denied and why

## Support

If modules aren't working:

1. Check `ENABLE_MODULE_LOADING=1` is set
2. Verify `module.toml` files exist and are valid TOML
3. Check module blueprints are importable
4. Review logs for import errors
5. Test module bootstrap with `pytest`
6. See [Module Development Guide](MODULE_DEVELOPMENT_GUIDE.md) for troubleshooting
