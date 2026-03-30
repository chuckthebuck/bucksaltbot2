# Quick Deployment Guide

## One-Minute Summary

✅ **Branch Status:** Ready for deployment  
✅ **Tests:** All passing (110 Python + 4 frontend)  
✅ **What's New:** Granular user permission management

## Quick Deployment (5 minutes)

```bash
# 1. On Toolforge
ssh toolforge
become buckbot
cd /data/project/buckbot

# 2. Ensure on feature branch (or merge to main first)
git checkout copilot/add-mediawiki-authorised-users

# 3. Deploy
./scripts/toolforge-deploy-new-version.sh

# 4. Verify
curl https://buckbot.toolforge.org/api/v1/rollback/worker
# Should return: {"status": "online", "last_seen": X}
```

## Environment Variables (Optional - All Default Safe)

Add to Toolforge `.env` or via buildpacks if you want these features:

```bash
EXTRA_AUTHORIZED_USERS=TestUser1,TestUser2    # Add test accounts
USERS_READ_ONLY=Viewer1,Viewer2               # View-only users
USERS_TESTER=Tester1,Tester2                  # Tester tier
RATE_LIMIT_JOBS_PER_HOUR=0                    # Enable rate limiting (0=off)
```

## What Changed

- **router.py**: +230 lines (new authorization logic)
- **test_router.py**: +812 lines (comprehensive tests)
- **No database changes**
- **Backward compatible**

## Rollback (If Needed)

```bash
git checkout main
./scripts/toolforge-deploy-new-version.sh
```

---

See `DEPLOYMENT_CHECKLIST.md` for full details.
