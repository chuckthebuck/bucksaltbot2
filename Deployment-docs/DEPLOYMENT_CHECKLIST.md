# Deployment Checklist: Add MediaWiki Authorised Users (Branch: `copilot/add-mediawiki-authorised-users`)

**Status:** ✅ Ready for Deployment  
**Date:** March 25, 2026

## Overview

This branch adds **granular user permissions and authorization controls** to BuckSaltBot2, allowing fine-grained access management without requiring full maintainer privileges.

### New Features

1. **User Authorization Levels**: Hierarchy of bot admin → maintainer → tester → admin → regular user
2. **Environment-Based User Management**: Add authorized users via environment variables
3. **Granular Permissions**: Per-user grants for specific interfaces (batch, from_diff, etc.)
4. **Read-Only Users**: Users who can only view their own jobs
5. **Rate Limiting**: Configurable per-hour job creation limits for different user tiers
6. **Cross-User Actions**: Controlled permissions for canceling/retrying other users' jobs

---

## Pre-Deployment Checks ✅

### Code Quality
- [x] All Python tests pass: **110/110 tests passing**
- [x] TypeScript compilation: **No errors**
- [x] ESLint: **No errors**
- [x] Frontend unit tests: **4/4 passing**
- [x] No syntax errors in any files

### Test Results Summary
```
Python Tests: 110 passed, 1 deprecation warning (harmless)
Frontend Tests: 4 passed
TypeScript: 0 errors
Lint: 0 errors
```

---

## Pre-Deployment Steps (Local)

### 1. ✅ Verify Branch State
```bash
git branch -v
# Should show: copilot/add-mediawiki-authorised-users
```

### 2. ✅ Run Full Test Suite
```bash
# Backend tests
python -m pytest tests/ -v

# Frontend tests
npm run test

# Type checking
npm run typecheck

# Linting
npm run lint
```

**Status: All passing** ✅

### 3. ✅ Review Changes
The branch modifies:
- **router.py**: +230 lines (new auth functions, permission checks, rate limiting)
- **tests/test_router.py**: +812 lines (comprehensive test coverage for new features)

No database migrations needed - all changes are in application logic.

---

## Environmental Variables Required for Deployment

Add these to your Toolforge environment variables (`.env` or Toolforge buildpacks config):

### New Required/Optional Variables

```bash
# Comma-separated list of individual MediaWiki usernames authorized to use the tool
# (without requiring full maintainer privileges)
EXTRA_AUTHORIZED_USERS=

# Comma-separated list of users who can only VIEW their own jobs (no submissions)
USERS_READ_ONLY=

# Comma-separated list of tester accounts (access to all tools, higher rate limit)
USERS_TESTER=

# Granular per-user interface grants (non-maintainer users)
USERS_GRANTED_FROM_DIFF=
USERS_GRANTED_VIEW_ALL=
USERS_GRANTED_BATCH=
USERS_GRANTED_CANCEL_ANY=
USERS_GRANTED_RETRY_ANY=

# Rate limiting configuration
# Set to 0 to disable rate limiting (maintainers bypass this always)
RATE_LIMIT_JOBS_PER_HOUR=0

# Separate rate limit for tester tier (falls back to RATE_LIMIT_JOBS_PER_HOUR if unset)
RATE_LIMIT_TESTER_JOBS_PER_HOUR=0
```

### Example Configuration

```bash
# Enable specific test users while keeping default rate limiting off
EXTRA_AUTHORIZED_USERS=TestUser42,TestAccount
USERS_TESTER=AliceTester,BobTester
USERS_GRANTED_FROM_DIFF=CharlieTesting
USERS_GRANTED_CANCEL_ANY=DaveSupport
```

---

## Deployment Steps

### Option 1: Deploy to Toolforge (Recommended)

```bash
# 1. Ensure you're on the feature branch
git checkout copilot/add-mediawiki-authorised-users

# 2. SSH to Toolforge
ssh toolforge

# 3. Navigate to your tool directory
become buckbot
cd /data/project/buckbot

# 4. Run the deployment script
BUILDPACK_CHANNEL=latest ./scripts/toolforge-deploy-new-version.sh

# 5. Monitor deployment logs
toolforge webservice buildservice logs -l 50
toolforge jobs logs -l 50 buckbot-celery

# 6. Verify services are running
toolforge jobs list

# 7. Test the service is up
curl https://buckbot.toolforge.org/api/v1/rollback/worker
# Should return: {"status": "online", "last_seen": <number>}
```

### Option 2: Manual Build (If Needed)

```bash
# From Toolforge shell while in /data/project/buckbot:
toolforge build start .

# Wait for build to complete, then:
toolforge webservice restart
toolforge jobs restart buckbot-celery
```

---

## Post-Deployment Verification

### 1. Check Service Health
```bash
# From your local machine
curl -s https://buckbot.toolforge.org/api/v1/rollback/worker | jq .
# Expected: {"status": "online", "last_seen": <number>}
```

### 2. Test Authorization
- Log in as a regular user → should see basic rollback queue
- Log in as a maintainer → should see all interfaces
- Verify new env vars are being respected (test users have correct access)

### 3. Check Logs
```bash
# Web service logs
ssh toolforge
become buckbot
toolforge webservice buildservice logs -l 100

# Celery worker logs
toolforge jobs logs -l 100 buckbot-celery
```

### 4. Test Rate Limiting (if enabled)
- Set `RATE_LIMIT_JOBS_PER_HOUR=5` and create 6+ jobs in an hour
- Request 6 should return **429 Too Many Requests** with message "Rate limit exceeded"

### 5. Test Granular Permissions
- Add a user to `USERS_GRANTED_FROM_DIFF` (but not `USERS_GRANTED_BATCH`)
- That user should see "Rollback from Diff" but not "Batch Rollback" in the UI

---

## Rollback Plan (If Issues Arise)

### Quick Rollback (< 10 minutes)
```bash
# 1. SSH to Toolforge
ssh toolforge
become buckbot

# 2. Revert to main branch
git checkout main
git pull origin main

# 3. Rebuild and restart
./scripts/toolforge-deploy-new-version.sh

# 4. Verify service is back
curl https://buckbot.toolforge.org/api/v1/rollback/worker
```

### If Database Issues Occur
- ✅ This deployment has **no database migrations** - it's safe to rollback
- All new features are in application code only

---

## New Features Documentation

### User Hierarchy (Highest to Lowest)

```
1. Bot Admin (chuckbot)
   → Can cancel maintainers' jobs
   → Full access to all features
   → Can be in BOT_ADMIN_ACCOUNTS env var

2. Maintainer (Toolhub registered)
   → Can cancel admins' jobs and regular users' jobs
   → Access to from_diff, batch, read_all
   → Exempt from rate limiting

3. Tester (USERS_TESTER env var)
   → Access to all interfaces (from_diff, batch, read_all)
   → Higher rate limit tier (RATE_LIMIT_TESTER_JOBS_PER_HOUR)
   → Cannot cancel/retry other users' jobs

4. Admin / Sysop (Commons admin right)
   → Basic authorization only
   → Can only submit rollback queue jobs

5. Regular User (rollbacker right)
   → Basic rollback queue access only
   → Can only submit and view own jobs

6. Extra Authorized (EXTRA_AUTHORIZED_USERS env var)
   → Same permissions as regular users (not full maintainer)
   → Useful for test accounts
```

### Permission Strings

| Permission | Meaning |
|---|---|
| `read_own` | View own jobs |
| `write` | Submit new jobs |
| `cancel_own` | Cancel own jobs |
| `retry_own` | Retry own jobs |
| `read_all` | View all users' jobs (all-jobs interface) |
| `from_diff` | Use rollback-from-diff interface |
| `batch` | Use batch rollback interface |
| `cancel_any` | Cancel regular users' jobs |
| `retry_any` | Retry any user's job |
| `cancel_admin_jobs` | Cancel admin/sysop users' jobs (maintainers only) |
| `cancel_maintainer_jobs` | Cancel maintainers' jobs (bot admins only) |

### Rate Limiting Behavior

```python
# Default: disabled (0 = no rate limiting)
RATE_LIMIT_JOBS_PER_HOUR=0

# Tiers:
# 1. Maintainers — NEVER rate limited
# 2. Testers — use RATE_LIMIT_TESTER_JOBS_PER_HOUR (or fallback to RATE_LIMIT_JOBS_PER_HOUR)
# 3. Regular users — use RATE_LIMIT_JOBS_PER_HOUR

# Redis bucket key format: rollback:ratelimit:{username}:{hour_bucket}
# Cleanup: 2-hour TTL auto-expires old buckets
# Fail-open: Redis outage doesn't block job submission
```

---

## Configuration Examples

### Scenario 1: Test Account Setup
```bash
EXTRA_AUTHORIZED_USERS=TestBot,TestUser42
USERS_TESTER=
USERS_GRANTED_FROM_DIFF=
USERS_GRANTED_VIEW_ALL=
USERS_GRANTED_BATCH=
USERS_GRANTED_CANCEL_ANY=
USERS_GRANTED_RETRY_ANY=
RATE_LIMIT_JOBS_PER_HOUR=0
```

### Scenario 2: Restrict Spam with Rate Limiting
```bash
EXTRA_AUTHORIZED_USERS=
USERS_TESTER=
RATE_LIMIT_JOBS_PER_HOUR=20      # Max 20 jobs/hour per user
RATE_LIMIT_TESTER_JOBS_PER_HOUR=50  # Testers: 50/hour
```

### Scenario 3: Grant Support Staff Limited Access
```bash
EXTRA_AUTHORIZED_USERS=Anna,Bob
USERS_GRANTED_CANCEL_ANY=Anna,Bob     # They can cancel regular users' jobs
USERS_GRANTED_RETRY_ANY=Anna           # Anna can retry any job
```

---

## Known Issues & Notes

### ⚠️ Deprecation Warning (Harmless)
```
DeprecationWarning: datetime.datetime.utcnow() is deprecated
```
- Location: `tests/test_router.py:479`
- Impact: Test-only, doesn't affect production
- Fix: Can be updated to use `datetime.now(datetime.UTC)` in future update

### ✅ No Breaking Changes
- Existing authorization still works (sysops + rollbackers + registered maintainers)
- New env vars are optional (all default to empty, no rate limiting by default)
- Backward compatible with current Toolforge setup

---

## Testing & Validation Checklist

After deployment, verify:

- [ ] Service is up: `curl https://buckbot.toolforge.org/api/v1/rollback/worker`
- [ ] Login works (Wikimedia OAuth)
- [ ] Regular users can submit jobs to rollback queue
- [ ] Maintainers can access all interfaces (from_diff, batch, all-jobs)
- [ ] Environment variables are being respected (check logs if configured)
- [ ] Celery worker is processing jobs (check job status)
- [ ] No errors in webservice logs
- [ ] No errors in Celery logs

---

## Support & Questions

If you encounter issues:

1. **Check logs first**: `toolforge webservice buildservice logs -l 200`
2. **Review environment variables**: Ensure they're set correctly on Toolforge
3. **Test locally**: Run tests locally before debugging on Toolforge
4. **Rollback if needed**: Quick rollback to `main` branch if critical issues

---

## Summary

**This branch is ready for deployment!**

✅ All tests passing  
✅ No database changes needed  
✅ Environment variables documented  
✅ Rollback plan in place  
✅ No breaking changes  

**Next Steps:**
1. Merge PR #66 to main (or deploy directly from this branch)
2. Add environment variables to Toolforge (optional, defaults safe)
3. Run deployment script on Toolforge
4. Verify services are healthy
5. Test new features with a test user account
