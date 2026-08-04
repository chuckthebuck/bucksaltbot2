# Deployment Checklist

Use this checklist for a framework commit that will be deployed to Toolforge.
The deployable unit is the framework revision plus the vendored module snapshots
stored in that revision.

## Commit gate

- [ ] `git status --short` contains only reviewed changes.
- [ ] `VERSION`, `package.json`, and the root `package-lock.json` records agree.
- [ ] `enabled-modules.txt` contains exactly the modules intended for this
  deployment.
- [ ] `requirements-modules.txt` installs every enabled external module from
  its committed `vendor/modules/<module>/` path.
- [ ] Any changed vendored snapshot has the expected upstream version and a
  current `SUBTREE.md` provenance note.
- [ ] Any changed module frontend has current compiled/package assets.
- [ ] The checked `jobs.yaml` generated block matches the schedules intended
  for production.

If the upstream module repositories changed, refresh their snapshots from a
clean framework checkout with:

```bash
npm run modules:update
```

Review the entire generated diff. The updater replaces the 4Award, File
Changer, and Salt Shack snapshots from their configured branches; it is not a
package-manager update and it is not a live subtree link.

## Verification gate

Run the module-owned tests for every module whose snapshot changed. Then run:

```bash
bash scripts/check-secrets.sh live
.venv/bin/python scripts/check-module-install.py
bash scripts/canary-build.sh
```

Set `CANARY_FULL_TESTS=1` for the full non-live framework suite when the change
touches shared routing, authorization, job control, database behavior, or the
module contract. The default canary does not run every test suite stored inside
each vendored module repository.

Preview framework-first module backports before publishing them:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
bash scripts/backport-chuck-file-changer-subtree.sh --dry-run
bash scripts/backport-chuck-salt-shack-subtree.sh --dry-run
```

The first two helpers use checked `git subtree split` output. Salt Shack uses a
checked clone-and-overlay preview. None of these commands refreshes the
framework's inbound snapshot.

## Schedule gate

Toolforge schedules come from the committed `jobs.yaml`, not directly from the
ToolsDB rows changed in the web UI.

- [ ] After a cron/config change, sign in as a module manager and open
  `/jobs-yaml`.
- [ ] Copy only the generated module-job block into the markers in
  `jobs.yaml`; preserve the framework-owned continuous and status jobs.
- [ ] Review and commit `jobs.yaml` before deploying.

The normal deploy wrapper flushes the current Toolforge job definitions and
loads the committed file. It does not regenerate that file from ToolsDB.

## Deploy

A push to `main` starts `.github/workflows/toolforge-deploy.yml`. A maintainer
can also dispatch that workflow for a reviewed branch and buildpack channel.
The workflow connects to the tool account and invokes
`scripts/toolforge-deploy-new-version.sh`, which:

1. Fast-forwards the checkout at `/data/project/buckbot`.
2. starts the Toolforge build for the selected branch;
3. restarts the buildservice webservice;
4. flushes Toolforge jobs; and
5. loads the committed `jobs.yaml` and lists the result.

Do not replace this with an undocumented sequence of local `pip`, `npm`, or
Gunicorn commands on Toolforge. Buildservice installs and starts the committed
bundle through `Procfile`.

## Post-deploy verification

- [ ] The GitHub deploy workflow and Toolforge build both completed.
- [ ] The webservice responds and a normal OAuth login succeeds.
- [ ] `/modules` lists the expected enabled modules for a maintainer.
- [ ] Each accessible module UI loads without missing asset errors.
- [ ] `/api/v1/modules` returns the expected registry while signed in.
- [ ] Salt Shack shows the expected discovered Saltlicks.
- [ ] File Changer's `/chuck_file_changer/api/auth` responds while signed in.
- [ ] Rollback worker health is current.
- [ ] `toolforge jobs list` includes `buckbot-celery`,
  `buckbot-module-controller`, the status job, and current generated schedules.
- [ ] Recent webservice, Celery, controller, and scheduled-job logs contain no
  new import, permission, or database errors.

## Incident rollback

Choose containment for the component that owns the work, then restore source by
reverting the bad framework commit and deploying that new `main` revision.
Generic disable/E-STOP blocks framework `module_job_runs` and targets scheduled
Toolforge work, but it does not stop a custom Blueprint or module-owned queue
such as File Changer's. Those incidents may require module-native controls or a
coordinated web/shared-worker stop and restart. `ENABLE_MODULE_LOADING=0` is the
whole-registry web-bootstrap opt-out and takes effect only after process restart.

Generic E-STOP cancels framework `module_job_runs` and tries to remove the
module's Toolforge jobs/pods. Rollback additionally purges the shared Buckbot
Celery queue, which can discard queued Salt Shack and File Changer task messages
as well as rollback messages. File Changer's durable
`chuck_file_change_jobs` rows are not canceled by the generic module E-STOP.
