# Chuck the Buckbot Framework Documentation Index

These files describe the current framework and deployment model. Module-owned
behavior belongs with the module package, while cross-module contracts and
Toolforge operations belong here.

## Start here

- [QUICKSTART.md](QUICKSTART.md) — safe first local run and everyday checks.
- [README.md](../README.md) — framework architecture, module contract, UI,
  authorization, and Toolforge flow.
- [MODULE_DEVELOPMENT_GUIDE.md](MODULE_DEVELOPMENT_GUIDE.md) — package a module,
  run it editable, refresh a deploy snapshot, declare jobs, and use framework
  services.
- [SALTLICK_AUTHORING_GUIDE.md](SALTLICK_AUTHORING_GUIDE.md) — create and review
  a Salt Shack workflow contract.

## Deployment and operations

- [TOOLFORGE_FIRST_DEPLOY.md](TOOLFORGE_FIRST_DEPLOY.md) — one-time checkout,
  secrets, schema, webservice, and jobs bootstrap.
- [RENAMING_AND_REPOSITORIES.md](RENAMING_AND_REPOSITORIES.md) — adopt the
  framework under a new tool name, create the required deployment repository,
  and point Build Service at it.
- [OWNERSHIP.md](OWNERSHIP.md) — authoritative ownership boundaries for
  framework code, modules, Build Service, schedules, and runtime state.
- [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) — release gate and
  post-deploy checks.
- [DEPLOYMENT_QUICK_REFERENCE.md](DEPLOYMENT_QUICK_REFERENCE.md) — compact
  command reference.
- [MODULE_DEPLOYMENT_PREP.md](MODULE_DEPLOYMENT_PREP.md) — module-specific
  deploy readiness and operational boundaries.
- [LOCAL_CANARY.md](LOCAL_CANARY.md) — local installs, service-aware checks,
  Docker, and safe-mode behavior.
- [ENVIRONMENT.md](ENVIRONMENT.md) — supported deploy environment and secret
  configuration.
- [VERSIONING.md](VERSIONING.md) — framework releases, standalone module
  releases, vendored snapshots, and bundle rollback.
- [ACCESS_CONTROL.md](ACCESS_CONTROL.md) — runtime groups, Wikimedia-role
  grants, module rights, and compatibility inputs.

## Module documentation

A module can reference packaged user documentation from its manifest:

```toml
[frontend]
docs = "package_name:docs/module_name.md"
```

The framework serves it at `/modules/<module>/docs` to users who can manage the
module or view its jobs. Current bundled module guides live in:

- `vendor/modules/four_award/modules/four_award/docs/four_award.md`
- `vendor/modules/chuck_file_changer/modules/chuck_file_changer/docs/chuck_file_changer.md`
- `vendor/modules/chuck_salt_shack/modules/chuck_salt_shack/docs/chuck_salt_shack.md`

## Current deployment authority

Normal production deployment is `.github/workflows/toolforge-deploy.yml`. It
runs on pushes to `main` and can be dispatched manually. The checked example
targets Buckbot, so an adopted deployment must first replace its tool account,
checkout path, and repository URL as described in the renaming guide. The
wrapper builds, restarts the webservice, flushes jobs, and loads the committed
`jobs.yaml` from that deployment repository.

Module schedule edits are two-step by design: update the registry state, then
use `/jobs-yaml` to review and commit the generated block before deployment.
Changing ToolsDB alone does not change a Toolforge schedule.

Delete obsolete branch notes or merge their still-valid facts into one of the
authoritative files above. Do not preserve old test counts, deprecated install
routes, or hypothetical deployment flows as current instructions.
