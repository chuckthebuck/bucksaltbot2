# Deployment Summary

Chuck the Buckbot deploys one versioned framework bundle through Toolforge
Build Service. The webservice, Celery worker, module run controller, status
cron, and generated module schedules all use source and module snapshots from
that same committed bundle.

## Bundle contents

- The framework owns Flask/OAuth, shared routing, authorization, ToolsDB and
  Redis integration, the module registry, generic jobs, and emergency controls.
- Rollback is framework-owned under `modules/rollback`.
- 4Award, File Changer, and Salt Shack are standalone repository snapshots
  committed below `vendor/modules` and installed by
  `requirements-modules.txt`.
- `enabled-modules.txt` selects manifests; `module-frontend-packages.json`
  selects source frontends compiled into the framework Vite bundle.
- `static/dist` is intentionally not committed. Toolforge's documented
  [Python-plus-Node Build Service behavior](https://wikitech.wikimedia.org/wiki/Help:Toolforge/Build_service#Using_Node.js_in_addition_to_another_language)
  detects the root `package.json`, and the documented
  [Node Cloud Native Buildpack flow](https://devcenter.heroku.com/articles/nodejs-cloud-native-buildpack-builds)
  runs its `build` script after dependency installation, producing the Vite
  manifest and hashed assets inside the image.
- Toolforge does not fetch a module repository at runtime or install modules
  through an API. The removed install endpoint remains a `410` compatibility
  response.

## Release path

1. Develop a standalone module in its own checkout and install it editable for
   local integration.
2. Refresh reviewed vendored snapshots with `npm run modules:update`.
3. Run the changed modules' tests and `bash scripts/canary-build.sh`.
4. If schedules changed, copy the reviewed `/jobs-yaml` output into the marked
   block in `jobs.yaml` and commit it.
5. Push the deploy commit to `main`. The Toolforge deploy GitHub workflow
   invokes `scripts/toolforge-deploy-new-version.sh`.

The wrapper fast-forwards `/data/project/buckbot`, starts a Build Service build,
restarts the webservice, flushes Toolforge jobs, and loads the committed
`jobs.yaml`. It does not regenerate schedules or initialize a new database;
those are first-deploy/bootstrap responsibilities.

## Runtime boundaries

Generic manual module runs are persisted in `module_job_runs` and claimed by
`buckbot-module-controller`. Scheduled handler jobs run through
`python3 -m module_runner`. Rollback and some module-owned APIs use Celery.

Disabling a module blocks generic run dispatch but does not unmount an already
registered custom Blueprint until restart. Generic E-STOP cancels generic
module rows and attempts to delete Toolforge jobs/pods; only Rollback has
additional built-in queue cleanup. Modules with separate queues, including
File Changer today, need separate stop handling.

Use [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) for the release gate and
[TOOLFORGE_FIRST_DEPLOY.md](TOOLFORGE_FIRST_DEPLOY.md) for a new tool account.
