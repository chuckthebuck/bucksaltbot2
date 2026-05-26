# Deployment Summary

Chuck the Buckbot Framework deploys as one Toolforge webservice plus
Toolforge-managed jobs. Module code is bundled into the framework deploy as
known-good package snapshots.

## Current Model

- The framework owns Flask, OAuth, shared APIs, ToolsDB state, Redis state,
  module registry, generated module rights, E-STOP controls, and jobs YAML
  generation.
- Rollback is the built-in framework module.
- External modules, such as 4Award, should live in their own repo and be
  vendored into this repo under `vendor/modules/<module>/` for deploy.
- Local development can use editable installs from a neighboring module clone.
  Vendoring is only needed when preparing a deployable framework commit.

## What Must Be True For Deploy

- `ENABLE_MODULE_LOADING=1` in the target environment.
- Required framework and module environment variables are configured.
- `requirements.txt` plus `requirements-modules.txt` install cleanly.
- `enabled-modules.txt` names only modules that should load.
- Module manifests declare only module-owned rights. The framework generates
  `module:<name>:view` and `module:<name>:estop`.
- Module-owned CTB APIs live under `/api/v1/modules/<module>/...`.
- Toolforge `jobs.yaml` has been updated if cron definitions changed.

## Useful Commands

```bash
python scripts/check-module-install.py
python3 -m pytest -q tests/test_module_registry.py tests/test_module_runtime.py
npm run build
bash scripts/check-secrets.sh live
```

For 4Award module work developed inside the framework:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
```

## Deployment Docs

Start with:

- [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)
- [MODULE_DEPLOYMENT_PREP.md](MODULE_DEPLOYMENT_PREP.md)
- [MODULE_DEVELOPMENT_GUIDE.md](MODULE_DEVELOPMENT_GUIDE.md)
- [VERSIONING.md](VERSIONING.md)
- [LOCAL_CANARY.md](LOCAL_CANARY.md)

Avoid using old branch-specific notes or old test-count claims as deployment
authority. Re-run the checks for the current branch instead.
