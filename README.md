# Chuck the Buckbot Framework

Chuck the Buckbot Framework is the Toolforge webservice and job-control layer
for Chuckbot modules. It started as rollback tooling, but the current goal is a
small framework that can run multiple independently owned and versioned bot
modules without making every module carry its own Flask, Redis, SQL, OAuth, and
Toolforge job-control code.

## Start Here

New contributors should begin with the [local quickstart](Deployment-docs/QUICKSTART.md).
It prepares isolated local services, explains the limits of local safe mode,
runs the focused canary, and starts the complete development stack. For the
complete documentation map, see the
[documentation index](Deployment-docs/DEPLOYMENT_DOCS_INDEX.md).

For a brand-new Toolforge account, use the reviewed
[first-deploy guide](Deployment-docs/TOOLFORGE_FIRST_DEPLOY.md). Salt Shack
workflow authors should use the
[Saltlick authoring guide](Deployment-docs/SALTLICK_AUTHORING_GUIDE.md).

## What Lives Here

- The Flask webservice, OAuth login, navigation, and shared APIs.
- Rollback, which remains the default built-in module.
- The default-enabled 4Award, File Changer, and Salt Shack package snapshots.
- Shared runtime state in ToolsDB and Redis.
- Module registry, module permission checks, module job runs, and emergency
  stop controls.
- Toolforge Jobs YAML generation from registered module cron jobs.

Module-specific business logic should live in the module package repo whenever
possible. For example, `chuck_the_4awardhelper` owns its parser, reviewer,
service code, Vue page, static build assets, and module documentation.

## Chuck the Salt Shack: Idea to Pywikibot in Under Two Hours

**Chuck the Salt Shack**—shown as **Salt Shack** in compact UI titles—is
Chuckbot's marquee module and is included in the default framework build. It
contains independently runnable Saltlicks. Each immediate child directory has
a Python entrypoint and may add a typed YAML contract for its inputs, outputs,
and framework actions. Without YAML, Salt Shack supplies a small read-only
default contract.

The build discovers those directories automatically, checks in a deterministic
registry snapshot for image review, and generates a nested Wikimedia Codex UI.
Wiki, namespace, page, multi-page,
choice, numeric, boolean, text, date, and user inputs are supported without a
Saltlick author writing frontend code. The browser sends only the Saltlick ID,
typed inputs, and compatibility arguments; it never sends script source or a
handler path.

Chuck the Salt Shack lives as the standalone-repository-shaped snapshot at
`vendor/modules/chuck_salt_shack/`, is installed by `requirements-modules.txt`, and is
listed in `enabled-modules.txt`. Preview runs produce a reviewed action-plan
token; apply runs must supply that token and reproduce the exact normalized
invocation and action plan. Every Saltlick also gets independent preview,
apply, and E-STOP rights. See
[`vendor/modules/chuck_salt_shack/README.md`](vendor/modules/chuck_salt_shack/README.md) for the
copy-a-directory workflow, contract format, API, and framework action model.

## Module Contract

Production modules are vendored package snapshots, not runtime-loaded plugins.
The deploy pins known-good framework code plus known-good module code together.
Local development does not need to use the vendored snapshot; install the module
repo in editable mode while you are working, then refresh the vendored snapshot
only when you are ready to make a deployable framework commit.

Python modules live under `vendor/modules/<module_name>/`, are installed by
local paths in `requirements-modules.txt`, and are registered only when their
module name appears in `enabled-modules.txt`:

```txt
# requirements-modules.txt
./vendor/modules/four_award
./vendor/modules/chuck_file_changer
./vendor/modules/chuck_salt_shack

# enabled-modules.txt
rollback
four_award
chuck_file_changer
chuck_salt_shack
```

The framework discovers and loads modules through:

1. **Vendored packages** — Modules expose an entry point in the
   `chuck_buckbot.modules` group and are listed in `enabled-modules.txt`
   (production model).
2. **Editable local packages** — During development, clone a module repo next to
   this framework repo and run
   `.venv/bin/python -m pip install -e ../module4awardhelper`
   inside the framework virtualenv. The same entry point is used, but changes in
   the module repo are picked up without copying code into `vendor/`.
3. **Framework-bundled modules** — A `module.toml` or `module.json` discovered
   under `modules/` for modules that genuinely live with the framework, such as
   rollback.

The framework validates module names, Python entry-point syntax, jobs, declared
rights, and frontend resource syntax while parsing manifests. The local canary
also verifies that referenced handler modules, frontend assets, and docs exist.

**Key constraints:**
- Module names are lowercase `snake_case` (e.g., `four_award`).
- Python handlers are dotted import paths (e.g., `package.service:run_job`).
- Manifests can be TOML or JSON.
- A `[frontend]` section requires `ui = true` and packaged static assets; a
  `ui = true` module may instead expose only its own Blueprint/web surface.
- Modules must declare a UI, at least one cron job, or at least one manual
  worker job.

**Manifest Example:**

```toml
name = "four_award"
title = "4awardhelper"
repo = "https://github.com/chuckthebuck/module4awardhelper"
entry_point = "chuck_the_4awardhelper.service:run_four_award_sync"
blueprint_entry_point = "chuck_the_4awardhelper.blueprint:blueprint"
ui = true
rights = ["manage", "run_jobs", "edit_config"]

[[jobs]]
name = "four-award-sync"
run = "every 15 minutes"
handler = "chuck_the_4awardhelper.service:run_four_award_sync"
execution_mode = "k8s_job"
timeout_seconds = 600

[frontend]
script = "chuck_the_4awardhelper:static/four-award-app.js"
styles = ["chuck_the_4awardhelper:static/style.css"]
props_id = "four-award-props"
mount_id = "app"
docs = "chuck_the_4awardhelper:docs/four_award.md"
```

**Important fields:**
- `name` — Lowercase snake_case identifier.
- `entry_point` — Dotted import path to a function, not a filename.
- `blueprint_entry_point` — Optional separate Flask Blueprint object/factory;
  job-only modules do not need one.
- `ui` — Boolean indicating a web surface. `[frontend]` is optional, but when
  present it requires `ui = true`.
- `jobs` — List of cron jobs. Each job needs `name`, `run` (human-readable or
  cron), and either `handler` (Python function) or `endpoint` (HTTP).
- `worker_jobs` — Manually queued handler jobs that do not need a cron schedule.
- `run` — Accepts `every 24 hours`, `every 15 minutes`, `daily at 03:00`, etc.
- `concurrency_policy` — `forbid` (default), `replace`, or `allow`.
- `required_right` — Optional module right required in addition to `run_jobs`
  for sensitive jobs. It must also be listed in `rights`.
- `rights` — Module-defined worker rights; become atoms like
  `module:four_award:run_jobs`. The framework automatically provides
  `module:<name>:view` and `module:<name>:estop`.

## CTB API Namespace

Framework-owned APIs are CTB APIs. In this codebase the current HTTP prefix is
`/api/v1`, for example:

```txt
/api/v1/modules
/api/v1/modules/<module>/config
/api/v1/modules/<module>/jobs
/api/v1/modules/<module>/estop
```

The framework generates the standard module management, config, jobs, run, and
E-STOP surfaces from the module registry. Module-owned CTB APIs may also live
under this namespace, but they should stay under their module path:

```txt
/api/v1/modules/<module>/<module-owned-resource>
```

Do not add new module APIs at top-level paths such as
`/api/v1/four-award/...`; those should move under `/api/v1/modules/four_award/`
over time. The current `/api/v1/four-award/...` routes and File Changer's
`/chuck_file_changer/api/...` routes are compatibility surfaces, not examples
for new modules. If a module needs to identify traffic to an external API such
as Wikimedia, keep that identity in module-owned config and request code, not
in a CTB route declaration.

4Award also retains an unsupported module-owned compatibility trigger at
`GET /four_award/api/v1/four_award/cron/run`. It is unauthenticated,
synchronous, and outside framework run tracking/runtime config. Production
schedules use the manifest handler through `module_runner`; do not expose or
integrate with the legacy route.

Legacy HTTP cron triggers require both `MODULE_CRON_BASE_URL` and
`MODULE_CRON_TOKEN`. Handler jobs are preferred because they run directly in an
isolated framework process and do not expose a public trigger endpoint.

## Module UI & Documentation

Framework Vue pages stay in this repo only for framework-owned screens (rollback,
etc.). Module pages belong entirely in the module repo.

For `bundled = true` frontends, add the module's source import to
`module-frontend-packages.json`. The current vendored modules use paths such as:

```json
{
  "name": "four_award",
  "enabled": true,
  "import": "../vendor/modules/four_award/modules/four_award/frontend/entry.ts"
}
```

`npm run build` regenerates `client-src/moduleRegistry.generated.ts` before
Vite builds. This is build-time static import, not dynamic runtime loading.
For `bundled = false`, the framework serves the packaged compiled JavaScript
and CSS through its authenticated module-asset route instead.

**Module UI Loading:**
1. Module declares `ui = true` in manifest.
2. Module declares `[frontend]` with `script`, optional `styles`, and an explicit
   `bundled` mode. The resource specs identify package-owned fallback/build
   artifacts; `bundled = false` serves them directly, while `bundled = true`
   loads the source entry already compiled into the framework's root bundle.
3. Framework serves module UI at `/modules/<module>/ui`.
4. Module UI receives JSON props in the DOM element named by `props_id`.

**Provided props:**
- `username`, `module`, `can_manage`, `can_run`, `can_view_jobs`, `can_edit_config`

**Module Documentation:**
1. Module declares `docs` in `[frontend]` (resource spec to a .md file).
2. Framework serves docs at `/modules/<module>/docs`.
3. Docs are visible to users who can manage the module or view module jobs.

Example manifest:
```toml
[frontend]
script = "chuck_the_4awardhelper:static/four-award-app.js"
styles = ["chuck_the_4awardhelper:static/style.css"]
props_id = "four-award-props"
mount_id = "app"
docs = "chuck_the_4awardhelper:docs/four_award.md"
```

## Permissions

Permissions are modeled as users, groups, and rights, similar to MediaWiki:

- Maintainers can manage the framework.
- Runtime groups grant framework rights such as `view_all` or `manage_modules`.
- Module rights use atoms like `module:four_award:run_jobs`.
- Modules declare their own right names; the framework decides how those rights
  are granted.
- `module:<name>:view` and `module:<name>:estop` are framework-generated rights,
  not module-declared rights.

`view_all` is treated as a broad job-viewing permission, including module job
views. Emergency stop is intentionally separate from disabling a module:
disable flips the registry flag, while E-STOP requests cancellation for
framework `module_job_runs`, attempts to delete scheduled Toolforge work, and
performs rollback-specific queue cleanup when stopping rollback. Modules with
their own queue tables need explicit cleanup wiring; there is no generic
module stop-hook call. Rollback's cleanup calls Celery's queue-wide purge on
the shared Buckbot queue, so it can also discard queued Salt Shack or File
Changer task messages; use that hard stop only with the shared blast radius in
mind.

## Toolforge Model

The webservice can update module registry rows and preview generated Jobs YAML,
but Toolforge still runs the checked-in `jobs.yaml`. The intended cron-change
flow is:

1. Edit module cron settings in the web UI.
2. Generate the new Jobs YAML from the framework.
3. Replace only the block between `# BEGIN GENERATED MODULE JOBS` and
   `# END GENERATED MODULE JOBS` in the repository's `jobs.yaml`.
4. Review and commit the file before deployment.

Pushes to `main` run `.github/workflows/toolforge-deploy.yml`. Its remote
wrapper updates `/data/project/buckbot`, builds the selected revision, restarts
the webservice, flushes the current Toolforge jobs, and reloads the committed
`jobs.yaml`. A manual deployment uses the same
`scripts/toolforge-deploy-new-version.sh` wrapper. Do not rely on a schedule
saved only in ToolsDB: it is not active in Toolforge until the generated YAML
has been committed and loaded.

Cron intervals should be human-readable in manifests and UI fields, for example
`every 24 hours`, `every 15 minutes`, or `daily at 03:00`.

## Local Development

Install dependencies, then validate and test:

```bash
# Backend tests
.venv/bin/python -m pytest -q tests --ignore=tests/live

# Frontend checks
npm run lint
npm run typecheck
npm run test

# Production build and module-resource canary
npm run build
bash scripts/canary-build.sh
```

**For module package development:**
1. Clone the module repo next to this repo.
2. Install it editable into the framework virtualenv:

   ```bash
   .venv/bin/python -m pip install -e ../module4awardhelper
   .venv/bin/python scripts/check-module-install.py
   ```

3. Match the frontend assembly mode in `module.toml`:
   - `bundled = false` (Salt Shack): build the sibling module so its packaged
     static assets are current.
   - `bundled = true` (4Award and File Changer): the framework Vite build imports
     the path in `module-frontend-packages.json`, which currently points at the
     vendored snapshot. Refresh that snapshot, or temporarily point the registry
     import at the sibling source for local-only iteration, then run the root
     build. An editable Python install alone does not redirect this import.
4. Run framework and module tests from whichever repo owns the behavior you
   changed.

For the lowest-setup framework-bundled Pywikibot module, scaffold a headless
handler directly:

```bash
.venv/bin/python scripts/create_pywikibot_module.py example_bot --enable
# Or add --schedule "every hour" for a cron handler.
```

This creates `modules/example_bot/module.toml` and `jobs.py`. Put the reviewed
Pywikibot workflow in `run(ctx, payload)`; the framework supplies OAuth,
configuration, logging, cancellation, timeout, concurrency, and run tracking.

When module behavior is ready to deploy, commit it in the module repo and then
refresh the repository-shaped snapshots in this repo. The checked refresh
command clones the configured source branches into temporary directories,
overlays only their vendored module roots, installs npm dependencies, and
regenerates the frontend registry:

```bash
npm run modules:update
```

Run that command only from a clean worktree; it refuses a dirty checkout. Source
remotes and branches can be overridden with the variables documented in
`scripts/update-vendored-modules.sh`. Toolforge deploys the resulting framework
snapshot and does not fetch module code separately.

### Toolforge GitHub Actions Deploy Key

The Toolforge deploy workflow uses a dedicated SSH key instead of your normal
Toolforge login key. Store the raw multiline private key contents in the
repository secret `TOOLFORGE_DEPLOY_PRIVATE_KEY`, and keep `TOOLFORGE_USERNAME`
set to the Toolforge shell username that can `become buckbot`.

Add the matching public key to the Toolforge/Wikimedia admin SSH key settings
for that Wikimedia developer account:

```bash
cat ~/.ssh/id_ed25519_toolforge_github_deploy.pub
```

Paste the output into the SSH key form at
<https://toolsadmin.wikimedia.org/profile/settings/ssh-keys> or
<https://idm.wikimedia.org/>. The key comment should make its purpose obvious,
for example `github-actions-buckbot-toolforge-deploy`.

For 4Award or File Changer changes developed directly in the vendored framework
copy, use the checked backport helper before pushing to the module repo:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
bash scripts/backport-chuck-file-changer-subtree.sh --dry-run
```

Each helper splits only its named vendored directory and refuses commits that
contain framework paths. The same workflow is available as VS Code tasks.

Chuck the Salt Shack has an equivalent checked backport for its independent
repository:

```bash
bash scripts/backport-chuck-salt-shack-subtree.sh --dry-run
```

It clones the target branch, overlays only `vendor/modules/chuck_salt_shack`,
and commits that Salt Shack-only diff. It defaults to
`https://github.com/chuckthebuck/chuck-the-salt-shack.git`; override
`CHUCK_SALT_SHACK_REMOTE` or `CHUCK_SALT_SHACK_BRANCH` when bootstrapping a
local repository or publishing through a fork.

## Documentation

Start with [Deployment-docs/DEPLOYMENT_DOCS_INDEX.md](Deployment-docs/DEPLOYMENT_DOCS_INDEX.md).
Module-specific docs should be packaged by the module and exposed through its
manifest `frontend.docs` field.
