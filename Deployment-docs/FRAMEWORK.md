# Reusable Bot Framework Boundary

This repository now exposes a small plugin boundary so other moderation bots can
reuse the same queue/orchestration stack.

## Required extension points

1. **BotAction** (`framework/action.py`)
   - Implement `execute_item(item_key, item_target, summary, requested_by, site, dry_run)`.
   - Register it in `app.py` with `register_action(...)`.

2. **BotPermissions** (`framework/permissions.py`)
   - Provide `domain_rights` and `domain_groups`.
   - Register it in `app.py` with `register_permissions(...)`.

3. **Identity/config** (`botconfig.py`)
   - Set bot identity, wiki/api URLs, docs/help links, DB suffix, and route prefix.

## What remains inherited

- OAuth/session handling
- Job queue and worker orchestration
- Approval/reject/force-dry-run/run-live flows
- Rate limiting and runtime authz config editor
- Cancel/retry endpoints

## Route prefix

Rollback API routes now resolve from:

- `BOT_ROUTE_PREFIX` (default: `rollback`)
- Effective pattern: `/api/v1/<BOT_ROUTE_PREFIX>/...`

Default behavior keeps all existing rollback URLs unchanged.

## DB naming

Queue tables are now generic:

- `bot_jobs`
- `bot_job_items`

Use `scripts/migrate_db.py` once to rename legacy tables (`rollback_jobs`,
`rollback_job_items`) on existing deployments.
