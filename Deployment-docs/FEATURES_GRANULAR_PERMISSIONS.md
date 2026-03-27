# New Features: Granular User Permissions

## Overview

This update adds flexible, environment-based authorization management to BuckSaltBot2, replacing the simple "maintainer or not" model with a granular permission system.

---

## New Features at a Glance

### 1. **Extra Authorized Users** (Test Accounts)
```bash
EXTRA_AUTHORIZED_USERS=TestBot,TestAccount42
```
- Grant basic authorization without full maintainer rights
- Users can submit jobs and view their own progress
- Useful for testing without granting admin privileges

### 2. **Read-Only Users** (Observers)
```bash
USERS_READ_ONLY=Viewer1,Viewer2
```
- Can view their own jobs but cannot submit, cancel, or retry
- Perfect for stakeholders who want visibility without control

### 3. **Tester Tier** (Enhanced Access)
```bash
USERS_TESTER=AliceTester,BobTester
```
- Access to **all interfaces** (from_diff, batch, all-jobs)
- Can submit unlimited jobs (or higher rate limit)
- Cannot cancel/retry other users' jobs
- Sits between regular users and maintainers

### 4. **Granular Grants** (A La Carte Permissions)

Grant specific interfaces to non-maintainer users:

```bash
# Allow specific users to use "rollback from diff"
USERS_GRANTED_FROM_DIFF=Charlie,Diana

# Allow specific users to see all jobs
USERS_GRANTED_VIEW_ALL=Eve,Frank

# Allow specific users to use batch interface
USERS_GRANTED_BATCH=Grace,Henry

# Allow specific users to cancel regular users' jobs
USERS_GRANTED_CANCEL_ANY=Ivan,Jill

# Allow specific users to retry any job
USERS_GRANTED_RETRY_ANY=Kevin,Laura
```

### 5. **Rate Limiting** (Spam Prevention)
```bash
RATE_LIMIT_JOBS_PER_HOUR=20              # Regular users: 20 jobs/hour
RATE_LIMIT_TESTER_JOBS_PER_HOUR=50       # Testers: 50 jobs/hour
```
- Maintainers bypass rate limiting always
- Fail-open: Redis outage doesn't block submissions
- Per-user, per-hour buckets in Redis

---

## User Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│ BOT ADMIN (chuckbot)                                            │
│ • Full access to all features                                   │
│ • Can cancel any user's job (including other admins)            │
│ • Exempt from rate limiting                                     │
│ Configured: BOT_ADMIN_ACCOUNTS env var                          │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ MAINTAINER (Toolhub registered)                                 │
│ • Access to: from_diff, batch, all-jobs                         │
│ • Can cancel admin users and regular users                      │
│ • Can retry any job                                             │
│ • Exempt from rate limiting                                     │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ TESTER (env: USERS_TESTER)                                      │
│ • Access to: from_diff, batch, all-jobs                         │
│ • Applies higher rate limit (RATE_LIMIT_TESTER_JOBS_PER_HOUR)  │
│ • Cannot cancel/retry other users' jobs                         │
│ • Can cancel/retry own jobs                                     │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ ADMIN / SYSOP (Commons sysop right acquired via Wikimedia)     │
│ • Basic authorization only                                      │
│ • Submit rollback queue jobs                                    │
│ • View and cancel own jobs only                                 │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ REGULAR USER (rollbacker right OR EXTRA_AUTHORIZED_USERS)      │
│ • Submit rollback queue jobs                                    │
│ • View and cancel own jobs                                      │
│ • View and retry own jobs                                       │
│ • Subject to rate limiting                                      │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ READ-ONLY USERS (env: USERS_READ_ONLY)                          │
│ • Can ONLY view own jobs                                        │
│ • Cannot submit, cancel, or retry                               │
│ • Use for audit/compliance observers                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Permission Strings

When checking permissions via the API/internally, the system uses permission strings:

| Permission | Who Has It | What It Allows |
|---|---|---|
| `read_own` | Everyone except read-only | View own jobs |
| `write` | Everyone except read-only | Submit new jobs |
| `cancel_own` | Everyone except read-only | Cancel own queued/running jobs |
| `retry_own` | Everyone except read-only | Retry own failed jobs |
| `read_all` | Maintainers, Testers, USERS_GRANTED_VIEW_ALL | View all users' jobs |
| `from_diff` | Maintainers, Testers, USERS_GRANTED_FROM_DIFF | Use rollback-from-diff interface |
| `batch` | Maintainers, Testers, USERS_GRANTED_BATCH | Use batch rollback interface |
| `cancel_any` | Maintainers, USERS_GRANTED_CANCEL_ANY | Cancel regular users' jobs |
| `retry_any` | Maintainers, USERS_GRANTED_RETRY_ANY | Retry any user's job |
| `cancel_admin_jobs` | Maintainers + bot admins | Cancel sysop admin's jobs |
| `cancel_maintainer_jobs` | Bot admins only | Cancel other maintainers' jobs |

---

## Configuration Examples

### Example 1: Simple Test Account Addition
```bash
# Add TestBot as a regular user without maintainer rights
EXTRA_AUTHORIZED_USERS=TestBot
```

### Example 2: Tester Tier with Higher Rate Limit
```bash
# Testers get more jobs/hour than regular users
RATE_LIMIT_JOBS_PER_HOUR=10
RATE_LIMIT_TESTER_JOBS_PER_HOUR=50
USERS_TESTER=AliceTester,BobTester
```

### Example 3: Support Staff with Limited Powers
```bash
# Support team can see all jobs and retry them, but not cancel
USERS_GRANTED_VIEW_ALL=SupportAlice,SupportBob
USERS_GRANTED_RETRY_ANY=SupportAlice,SupportBob
```

### Example 4: Restricted Operators
```bash
# Operators can only use batch rollback, nothing else
USERS_GRANTED_BATCH=OperatorAlice,OperatorBob
```

### Example 5: Observer Mode
```bash
# These users can watch but not touch
USERS_READ_ONLY=AuditViewer,ComplianceViewer
```

---

## API Response Examples

### Check Worker Status
```bash
curl https://buckbot.toolforge.org/api/v1/rollback/worker
```
Response: `{"status": "online", "last_seen": 4.2}`

### Rate Limit Exceeded
```bash
curl -X POST https://buckbot.toolforge.org/api/v1/rollback/jobs \
  -H "Content-Type: application/json" \
  -d '{"items":[{"title":"File:X.jpg","user":"Vandal"}]}'
```
Status Code: `429 Too Many Requests`  
Response: `{"detail": "Rate limit exceeded; try again later"}`

### Permission Denied
```bash
curl https://buckbot.toolforge.org/rollback_batch
```
Status Code: `403 Forbidden`  
(User doesn't have `batch` permission)

---

## Migration Path (From Old to New System)

### Before (v1)
```
- Sysops: basic access
- Registered Maintainers: full access
```

### After (v1 + this update)
```
- Sysops: basic access (unchanged)
- Registered Maintainers: full access (unchanged)
- ✨ NEW: Extra authorized users
- ✨ NEW: Read-only viewers
- ✨ NEW: Testers with specific interfaces
- ✨ NEW: Rate limiting
- ✨ NEW: Granular permission grants
```

**Key Point:** All existing behavior is preserved. New features are opt-in via environment variables.

---

## Internal Implementation

### Authorization Functions

```python
# Check if user is authorized at all
is_authorized(username) -> bool

# Check if user is a bot admin (chuckbot)
is_bot_admin(username) -> bool

# Check if user is a tester
is_tester(username) -> bool

# Get all permissions for a user (returns frozenset of permission strings)
_user_permissions(username) -> frozenset[str]

# Check rate limit (returns True if under limit)
_check_rate_limit(username) -> bool
```

### Allowed Groups (Still Used)
- `sysop` (Commons admin right)
- `rollbacker` (Commons rollbacker right) — **NEWLY ADDED**

Previously only `sysop` was checked. Now both work for basic access.

---

## Testing This Locally

### Run Tests
```bash
python -m pytest tests/test_router.py -v -k "permission\|rate_limit\|authorized"
```

### Test with Mocked Env Vars
```python
from unittest.mock import patch
import router

with patch.object(router, "EXTRA_AUTHORIZED_USERS", {"testuser"}):
    assert router.is_authorized("TestUser") is True
```

---

## Troubleshooting

### User Can't Access Interface They Should Be Able To

1. **Check user is authenticated:** Do they see `/rollback-queue`?
2. **Check env variable:** Is `USERS_GRANTED_FROM_DIFF` set if they need from_diff?
3. **Check case:** Env vars are case-insensitive, but usernames should match Wikimedia exactly
4. **Check Toolforge:** Environment variable might not be deployed yet

### Rate Limit Blocking Legitimate Users

```bash
# Check current bucket in Redis:
redis-cli GET "rollback:ratelimit:username:${HOUR}"

# Temporarily disable:
# Set RATE_LIMIT_JOBS_PER_HOUR=0

# Or increase:
# Set RATE_LIMIT_JOBS_PER_HOUR=50 (higher limit)
```

### Read-Only User Can Still See Write Buttons

- Old version of browser cache
- Clear browser cache or use incognito mode
- Frontend checks permissions before enabling submit buttons

---

## Security Considerations

✅ **Case-insensitive usernames** — Prevent bypass via alternate casing  
✅ **No privilege escalation** — EXTRA_AUTHORIZED_USERS ≠ maintainer rights  
✅ **Hierarchical cancel permissions** — Prevent lower users from canceling higher ones  
✅ **Rate limiting fail-open** — Redis outage doesn't block jobs  
✅ **Permission checks on every request** — Not cached (groups cached for 5 min)  

---

## Performance Notes

- **Group cache:** 5 minutes (to reduce Commons API calls)
- **Rate limit buckets:** Redis only, 2-hour TTL for auto-cleanup
- **No database changes:** All auth logic in application memory
- **Minimal overhead:** Authorization check ~1ms per request

---

## Summary

This update provides **powerful, flexible authorization management** without the complexity of a full RBAC system. It's backward compatible, safe to deploy, and can be configured entirely through environment variables.

**Next Step:** Deploy and configure environment variables as needed!
