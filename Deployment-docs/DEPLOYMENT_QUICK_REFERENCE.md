# Deployment Quick Reference

## Local Checks

```bash
python scripts/check-module-install.py
python3 -m pytest -q tests/test_module_registry.py tests/test_module_runtime.py
npm run build
bash scripts/check-secrets.sh live
```

Run narrower or broader test commands based on what changed. Do not rely on old
stored test counts.

## Toolforge Deploy

```bash
ssh login.toolforge.org
become buckbot
cd /data/project/buckbot
git pull --ff-only
toolforge build start https://github.com/<owner>/<repo>
toolforge webservice buildservice restart
```

## Cron Changes

```bash
toolforge jobs load jobs.yaml
toolforge jobs list
```

The framework can generate jobs YAML from module registry state, but Toolforge
still needs `jobs.yaml` loaded explicitly.

## Core Environment

```bash
ENABLE_MODULE_LOADING=1
TOOL_DATA_DIR=/data/project/buckbot
NOTDEV=1
```

Framework and module User-Agent defaults derive their version from the deployed
release. Set the `*_HTTP_USER_AGENT` variables only when a deployment needs a
full custom override.

See [ENVIRONMENT.md](ENVIRONMENT.md) for the full environment-variable map.

## Module API Rule

Framework-generated module APIs live under:

```txt
/api/v1/modules/<module>/...
```

Module-owned CTB APIs should also stay under that module path. Avoid new
top-level module paths such as `/api/v1/four-award/...`.

## Rollback

For a module-specific problem, disable the module or set
`ENABLE_MODULE_LOADING=0` and restart. For a framework-wide problem, redeploy the
last known-good commit and reload `jobs.yaml` if job definitions changed.
