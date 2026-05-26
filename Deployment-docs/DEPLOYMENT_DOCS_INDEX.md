# Chuck the Buckbot Framework Documentation Index

This folder is now framework documentation, not a deployment snapshot for one
old branch. Prefer current docs here and module-owned docs inside module
packages.

## Start Here

- [README.md](../README.md) — Current framework overview, module contract, UI
  ownership, permission model, and Toolforge flow.
- [MODULE_DEVELOPMENT_GUIDE.md](MODULE_DEVELOPMENT_GUIDE.md) — How to build a
  module package, install it editable for local development, refresh a vendored
  snapshot for deploys, declare cron jobs, expose rights, and use framework
  services.
- [MODULE_DEPLOYMENT_PREP.md](MODULE_DEPLOYMENT_PREP.md) — Toolforge-oriented
  deployment prep for packaged modules.
- [LOCAL_CANARY.md](LOCAL_CANARY.md) — Local install, module install, and canary
  build scripts to run before pushing to Toolforge.
- [VERSIONING.md](VERSIONING.md) — Framework, module, vendored snapshot, and
  deploy-bundle versioning rules.
- [ACCESS_CONTROL.md](ACCESS_CONTROL.md) — Runtime groups, auto grants, and
  MediaWiki-style rights handling.
- [FEATURES_GRANULAR_PERMISSIONS.md](FEATURES_GRANULAR_PERMISSIONS.md) —
  Detailed permission examples and migration notes.

## Module Documentation

Module documentation should ship with the module package and be referenced from
the module manifest:

```toml
[frontend]
docs = "package_name:docs/module_name.md"
```

The framework serves that page at `/modules/<module>/docs` for users who can
manage the module or view that module's jobs.

## Toolforge Deployment Notes

For normal framework deployment:

```bash
ssh login.toolforge.org
become buckbot
cd /data/project/buckbot
git pull --ff-only
toolforge build start https://github.com/<owner>/<repo>
toolforge webservice buildservice restart
```

For cron changes:

1. Update module cron settings in the webservice.
2. Generate Jobs YAML from the webservice.
3. Update the tool account's `jobs.yaml`.
4. Run `toolforge jobs load jobs.yaml`.

The framework can generate the YAML from SQL state. Toolforge still needs the
file loaded because Toolforge jobs are not live-edited by the buildpack.

## Documentation Cleanup Rule

If a doc describes an old branch, stale test count, or old rollback-only access
model, update it before linking it from the web UI. If it is only historical,
move the useful facts into one of the current docs and remove the stale file.
