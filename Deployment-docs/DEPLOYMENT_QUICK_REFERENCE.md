# Deployment Quick Reference

## Local release checks

```bash
bash scripts/check-secrets.sh live
.venv/bin/python scripts/check-module-install.py
bash scripts/canary-build.sh
```

The default canary validates the framework, enabled manifests, generated Salt
Shack registry, frontend registry/build, and focused framework integration
tests. Run changed modules' own tests separately. For the full non-live
framework suite:

```bash
CANARY_FULL_TESTS=1 bash scripts/canary-build.sh
```

## Vendored module refresh

From a clean framework worktree:

```bash
npm run modules:update
```

This clone-and-overlay refresh currently updates 4Award from `framework-dev`
and File Changer and Salt Shack from `main`, unless their `*_REMOTE` or
`*_BRANCH` overrides are set. Review and test the complete snapshot diff.

## Cron changes

1. Update the module schedule/config through the signed-in web UI.
2. Open `/jobs-yaml` as a module manager.
3. Replace only the generated block in the checked `jobs.yaml`.
4. Review and commit the file before deployment.

For an intentional exact jobs-only reconciliation from the Toolforge checkout,
accept a brief interruption to continuous jobs and run:

```bash
toolforge jobs flush
toolforge jobs load jobs.yaml
toolforge jobs list
```

The flush matters when a definition was removed or renamed; `load` alone may
leave stale jobs running. The normal deploy wrapper already performs this exact
flush/reload sequence.

## Production deploy

Push the reviewed commit to `main`, or manually dispatch the **Toolforge
deploy** GitHub workflow for a reviewed branch. It builds the repository that
contains the workflow and runs the wrapper in `/data/project/<tool-name>`.
The checked workflow still uses `buckbot`; adopters must rename its Toolforge
account/path and image references as documented in
[RENAMING_AND_REPOSITORIES.md](RENAMING_AND_REPOSITORIES.md).

For an operator-run recovery deploy after becoming the tool account:

```bash
cd /data/project/<tool-name>
REPO_DIR=/data/project/<tool-name> \
REPO_URL=https://github.com/<owner>/<framework-deployment-repo>.git \
BRANCH=main BUILDPACK_CHANNEL=latest \
  bash scripts/toolforge-deploy-new-version.sh
```

## Core production environment

```text
BOT_NAME=<tool-name>
ENABLE_MODULE_LOADING=1
NOTDEV=1
BUCKBOT_REDIS_NAMESPACE=<tool-name>
BUCKBOT_CELERY_QUEUE=<tool-name>.celery
BUCKBOT_CELERY_WORKER_NAME=<tool-name>-celery
```

Secrets and OAuth credentials are managed with Toolforge envvars. See
[ENVIRONMENT.md](ENVIRONMENT.md); do not store them in Git or `jobs.yaml`.

## Incident controls

- Use disable/E-STOP for framework-owned run rows and scheduled Toolforge work;
  check the module's own queue/API boundary before treating it as containment.
- Set `ENABLE_MODULE_LOADING=0` and restart web processes to suppress module
  Blueprint bootstrap; coordinate shared-worker shutdown separately if needed.
- Revert a bad framework/snapshot commit on `main` and let the normal workflow
  redeploy the restored bundle.

E-STOP coverage ends at framework-managed run rows and Toolforge jobs unless a
module implements additional cleanup. File Changer's separate Celery/table
queue and already-mounted API are not stopped by generic module E-STOP today.
Rollback E-STOP is broader in a different direction: it purges the shared
Buckbot Celery queue and may discard queued Salt Shack or File Changer messages.
