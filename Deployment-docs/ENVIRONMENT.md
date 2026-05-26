# Environment And Secrets

Chuckbot uses environment variables for deploy-time configuration. Keep secrets
out of git: local values belong in `.env`, and Toolforge values belong in the
tool account environment/buildservice configuration.

Before a local canary:

```bash
bash scripts/check-secrets.sh canary
```

Before a live Toolforge deploy:

```bash
bash scripts/check-secrets.sh live
```

The checker only reports whether values are present; it never prints secret
contents.

## Secret Values

These should not be committed.

| Name | Scope | Notes |
| --- | --- | --- |
| `SECRET_KEY` | framework web | Flask session signing key. Required for live. |
| `USER_OAUTH_CONSUMER_KEY` | framework web | OAuth login consumer key. Required for live login. |
| `USER_OAUTH_CONSUMER_SECRET` | framework web | OAuth login consumer secret. Required for live login. |
| `CONSUMER_TOKEN` | wiki writes | Pywikibot OAuth consumer token for bot edits. |
| `CONSUMER_SECRET` | wiki writes | Pywikibot OAuth consumer secret for bot edits. |
| `ACCESS_TOKEN` | wiki writes | Pywikibot OAuth access token for bot edits. |
| `ACCESS_SECRET` | wiki writes | Pywikibot OAuth access secret for bot edits. |
| `TOOL_TOOLSDB_PASSWORD` | Toolforge/local DB | MariaDB password. Toolforge buildservice can provide this through env when `replica.my.cnf` is not mounted. |

## Non-Secret Runtime Config

These are safe to document and usually safe to keep in `.env.example`.

| Name | Scope | Notes |
| --- | --- | --- |
| `ENABLE_MODULE_LOADING` | framework | Enables module registry bootstrap. |
| `ENABLED_MODULES` | framework | Optional override; empty uses `enabled-modules.txt`. |
| `BOT_NAME` / `TOOL_NAME` | framework | Tool identity and default callback host. |
| `NOTDEV` | framework | Production flag used by deployment/runtime scripts. |
| `BUCKBOT_HTTP_USER_AGENT` | framework HTTP | User-Agent for framework-owned Wikimedia/Toolhub requests. |
| `FOUR_AWARD_HTTP_USER_AGENT` | 4Award module HTTP | User-Agent for 4Award-owned Wikimedia requests. |
| `TOOL_REDIS_URI` | services | Redis URL for framework status/progress state. |
| `CELERY_BROKER_URL` | services | Celery broker URL. |
| `CELERY_RESULT_BACKEND` | services | Celery result backend URL. |
| `TOOL_TOOLSDB_HOST` | DB | Optional DB host override. Toolforge defaults to `tools.db.svc.wikimedia.cloud`; local canary defaults to `127.0.0.1`. |
| `TOOL_TOOLSDB_USER` | DB | DB user override. |
| `TOOL_TOOLSDB_DATABASE` | DB | DB name override. |
| `TOOL_DATA_DIR` | filesystem | Runtime data/log root. |
| `PYWIKIBOT_DIR` | filesystem | Pywikibot config directory. |

## Policy

Use environment variables for secrets and deploy-specific hostnames. Use module
config/runtime UI for operational toggles that maintainers may change without
rotating credentials.
