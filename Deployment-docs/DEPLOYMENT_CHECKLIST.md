# Deployment Checklist

Use this checklist before deploying the framework to Toolforge. This file is a
living checklist for the current framework/module model, not a snapshot of one
old feature branch.

## Before Deploying

- [ ] Confirm the branch you intend to deploy is up to date.
- [ ] Review `git status --short` and make sure only intended changes are
  included.
- [ ] Run the focused backend tests for the areas you changed.
- [ ] Run the module-owned tests for any vendored module you changed.
- [ ] Run `npm run build` if framework or module frontend assets changed.
- [ ] Check required secrets without printing values:

  ```bash
  bash scripts/check-secrets.sh live
  ```

## Module Checks

- [ ] `enabled-modules.txt` lists every module that should load.
- [ ] `requirements-modules.txt` pins every vendored module path needed for
  deploy.
- [ ] Each enabled module imports cleanly:

  ```bash
  python scripts/check-module-install.py
  ```

- [ ] Vendored module snapshots under `vendor/modules/<module>/` contain only
  module repo files, not framework files.
- [ ] If a module has a frontend, its built static assets are committed under
  the module package.
- [ ] If cron schedules changed, regenerate and load Toolforge `jobs.yaml`.

## 4Award Backport Check

When changing the 4Award module inside this framework repo, preview the subtree
split before pushing back to the module repo:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
```

The split should show the module repo root (`modules/`, `tests/`,
`pyproject.toml`, package files, and module docs). It should not include
framework paths such as `router/`, `Deployment-docs/`, `vendor/`, or
`requirements.txt`.

## Toolforge Deploy

From the tool account:

```bash
ssh login.toolforge.org
become buckbot
cd /data/project/buckbot
git pull --ff-only
toolforge build start https://github.com/<owner>/<repo>
toolforge webservice buildservice restart
```

If cron jobs changed:

```bash
toolforge jobs load jobs.yaml
toolforge jobs list
```

## Post-Deploy Verification

- [ ] Webservice responds.
- [ ] `/api/v1/modules` lists the expected enabled modules.
- [ ] Maintainer UI can open `/modules`.
- [ ] Module UI pages load without static asset errors.
- [ ] Rollback worker health endpoint responds.
- [ ] Module controller and Toolforge jobs are present.
- [ ] Recent webservice and job logs have no new import or permission errors.

## Rollback

If the failure is module-specific, disable the module in the admin UI or set
`ENABLE_MODULE_LOADING=0` and restart while you investigate. If the failure is
framework-wide, revert or redeploy the last known-good framework commit, then
reload `jobs.yaml` if job definitions changed.
