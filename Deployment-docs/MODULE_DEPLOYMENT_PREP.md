# Module Deployment Preparation

This is the operational checklist for shipping packaged modules with the
framework. Use [MODULE_DEVELOPMENT_GUIDE.md](MODULE_DEVELOPMENT_GUIDE.md) for
package/manifest design and
[DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) for the release gate.

## Confirm the bundle

The current deploy contains built-in Rollback plus vendored 4Award, File
Changer, and Salt Shack. External modules are committed repository snapshots;
Toolforge does not clone them at build time, and the removed remote-install API
returns `410`.

Refresh upstream snapshots from a clean worktree with:

```bash
npm run modules:update
```

Review the entire replacement diff, versions, compiled assets, and `SUBTREE.md`
metadata. Defaults are 4Award `framework-dev`, File Changer `main`, and Salt
Shack `main`; use `*_REMOTE`/`*_BRANCH` overrides only for reviewed sources.

## Verify installation and manifests

`requirements-modules.txt`, `enabled-modules.txt`, package
`chuck_buckbot.modules` entry points, manifests, and frontend registry entries
must agree. Run:

```bash
bash scripts/install-framework.sh
bash scripts/install-modules.sh
.venv/bin/python scripts/check-module-install.py
bash scripts/canary-build.sh
```

Run each changed module's own backend/frontend tests too. The default canary
runs focused integration coverage, not every vendored test suite.

## Know the execution owner

| Work | Current owner |
| --- | --- |
| Scheduled manifest handler | Toolforge schedule runs `python3 -m module_runner`. |
| Generic manual manifest run | `buckbot-module-controller` claims a `queued` `module_job_runs` row and starts `module_runner`. |
| Rollback work | Shared Celery worker and rollback-owned tables. |
| Salt Shack custom API | Celery task atomically claims a framework module run row. |
| File Changer preview/apply | Celery task processes separate File Changer job/item tables. |

Manifest `handler` and `k8s_job` execution modes currently generate the same
Toolforge command. `http` is a token-protected compatibility mode.

## Module checks

### Rollback

- Open `/rollback/` while signed in.
- Verify submission, review/approval, dry-run/live controls, and worker health.
- Confirm `buckbot-celery` consumes only this deployment's queue.

### 4Award

- Confirm `/modules/four_award/ui` mounts the Four Award entry compiled into the
  framework's root Vite bundle. Its packaged static artifact is not the runtime
  source while `frontend.bundled = true`.
- Run a historical-diff dry run and inspect the records-table preview.
- Keep runtime `dry_run` enabled until action switches and automated approval
  are reviewed separately.
- Confirm the generated `four-award-sync` schedule.

### File Changer

- Confirm `/chuck_file_changer/api/auth` reports expected signed-in rights.
- Test manual and one remote/VFC-style source.
- Preview a no-op and changed target before testing apply.
- Verify chunk rows and Celery progress.
- Remember generic E-STOP does not cancel its separate
  `chuck_file_change_jobs` rows today.

### Salt Shack

- Run the generated-registry check and module-owned tests.
- Confirm intended child directories and contracts are discovered.
- Preview read-only and mutation Saltlicks in local safe mode.
- Verify apply requires matching preview token plus live confirmation.
- Verify per-Saltlick rights/E-STOP affect only that Saltlick.

## UI and authorization checks

Use signed-in browser sessions for a maintainer, a scoped module user, and a
denied user. Unauthenticated `curl` does not prove behavior.

- `/modules` is the generic registry page.
- `/modules/<module>/ui` is the generic UI shell.
- `/api/v1/modules/...` contains generic APIs and Salt Shack's owned namespace.
- File Changer retains `/chuck_file_changer/api/...` for compatibility.
- New module APIs should stay under `/api/v1/modules/<module>/...`.

The framework generates `view` and `estop`; manifests declare operation rights.
Salt Shack also generates per-Saltlick preview/apply/E-STOP rights.

Disabling blocks generic dispatch but does not unmount an already registered
custom Blueprint until restart. Custom endpoints must enforce current state and
authorization themselves.

## Commit schedules

ToolsDB cron state is not a live Toolforge scheduler API. After a change, open
`/jobs-yaml`, review the output, replace only the marked generated block in
repository `jobs.yaml`, and commit it. The normal wrapper flushes and reloads
that committed file.

For an intentional exact jobs-only reconciliation from the tool checkout:

```bash
toolforge jobs flush
toolforge jobs load jobs.yaml
toolforge jobs list
```

This briefly interrupts continuous jobs. Do not use `load` alone to remove or
rename a definition: stale Toolforge jobs may remain active.

## Deploy and contain incidents

Push the reviewed commit to `main` or dispatch the Toolforge deploy workflow.
Build Service owns dependency installation and `Procfile` process startup; do
not create a parallel manual Gunicorn/Celery production stack.

Contain incidents at the smallest scope. Per-Saltlick E-STOP affects one
Saltlick. Generic E-STOP disables a module, requests cancellation of active
`module_job_runs`, and attempts Toolforge job/pod deletion. Rollback additionally
purges the shared Buckbot Celery queue, which can discard queued Salt Shack and
File Changer messages as well as Rollback work. File Changer has the opposite
boundary: its custom table/Celery queue and already-mounted API are not stopped
by generic E-STOP, so use module-native controls or a coordinated web/worker
restart. `ENABLE_MODULE_LOADING=0` suppresses all module bootstrap only after
restart.

There is no generic module stop hook. After containment, revert the faulty
framework/snapshot commit, rerun the canary, and deploy the restored `main`
bundle.
