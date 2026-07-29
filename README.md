# Chuck the Buckbot Framework

Chuck the Buckbot Framework is the Toolforge webservice and job-control layer
for Chuckbot modules. It started as rollback tooling, but the current goal is a
small framework that can run multiple independently deployable bot modules
without making every module carry its own Flask, Redis, SQL, OAuth, and
Toolforge job-control code.

## What Lives Here

- The Flask webservice, OAuth login, navigation, and shared APIs.
- Rollback, which remains the default built-in module.
- Shared runtime state in ToolsDB and Redis.
- Module registry, module permission checks, module job runs, and emergency
  stop controls.
- Toolforge Jobs YAML generation from registered module cron jobs.

Module-specific business logic should live in the module package repo whenever
possible. For example, `chuck_the_4awardhelper` owns its parser, reviewer,
service code, Vue page, static build assets, and module documentation.

## Saltlick: Idea to Pywikibot in Under Two Hours

Saltlick is Chuckbot's marquee module and is included in the default framework
build. Its guided workshop lets a contributor choose real Pywikibot page
generators, chain text transformations, filter and bound the run, preview every
proposed edit as a unified diff, and then either run live or export a fork-ready
recipe, handler, and manifest.

The shared-host version favors features without pretending arbitrary Python is
safe to execute beside framework credentials. It includes literal and regex
changes, full-page templates, and a restricted Python-like expression language.
When that boundary becomes limiting, the generated source is designed to be
edited as normal Python in a Saltlick fork.

Saltlick lives as the standalone package snapshot at
`vendor/modules/saltlick/`, is installed by `requirements-modules.txt`, and is
listed in `enabled-modules.txt`. Its preview job cannot save; live execution has
the separate `module:saltlick:apply_changes` permission and explicit
confirmation gates. See
[`vendor/modules/saltlick/README.md`](vendor/modules/saltlick/README.md) for the
two-hour path, CLI, supported sources and transformations, and fork workflow.

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
./vendor/modules/saltlick

# enabled-modules.txt
rollback
four_award
saltlick
```

The framework discovers and loads modules through:

1. **Vendored packages** — Modules expose an entry point in the
   `chuck_buckbot.modules` group and are listed in `enabled-modules.txt`
   (production model).
2. **Editable local packages** — During development, clone a module repo next to
   this framework repo and run `python -m pip install -e ../module4awardhelper`
   inside the framework virtualenv. The same entry point is used, but changes in
   the module repo are picked up without copying code into `vendor/`.
3. **Framework-bundled modules** — A `module.toml` or `module.json` discovered
   under `modules/` for modules that genuinely live with the framework, such as
   rollback.

The framework validates module names, Python entry points, cron jobs, declared
rights, frontend asset references, and documentation references before loading.

**Key constraints:**
- Module names are lowercase `snake_case` (e.g., `four_award`).
- Python handlers are dotted import paths (e.g., `package.service:run_job`).
- Manifests can be TOML or JSON.
- Frontend requires `ui = true` and packaged static assets.
- Modules must declare either a UI or at least one cron job.

**Manifest Example:**

```toml
name = "four_award"
title = "Chuck the 4awardhelper"
repo = "https://github.com/chuckthebuck/module4awardhelper"
entry_point = "chuck_the_4awardhelper.service:run_four_award_sync"
blueprint_entry_point = "chuck_the_4awardhelper.blueprint:blueprint"
ui = true
rights = ["manage", "run_jobs", "edit_config"]

[[jobs]]
name = "four-award-sync"
run = "every 24 hours"
handler = "chuck_the_4awardhelper.service:run_four_award_sync"
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
- `ui` — Boolean; if true, module must declare `[frontend]`.
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
over time. If a module needs to identify traffic to an external API such as
Wikimedia, put that in module-owned runtime config or a future manifest
`external_api` section, not as a CTB route.

Legacy HTTP cron triggers require both `MODULE_CRON_BASE_URL` and
`MODULE_CRON_TOKEN`. Handler jobs are preferred because they run directly in an
isolated framework process and do not expose a public trigger endpoint.

## Module UI & Documentation

Framework Vue pages stay in this repo only for framework-owned screens (rollback,
etc.). Module pages belong entirely in the module repo.

If a module ships a separate npm/Vue client package, pin it in `package.json`
with normal npm syntax and add the import path to
`module-frontend-packages.json`. `npm run build` regenerates
`client-src/moduleRegistry.generated.ts` before Vite builds. This is still
build-time static import, not dynamic runtime loading.

```json
{
  "dependencies": {
    "@chuckbot/4award": "github:chuckthebuck/chuckbot-4award#v0.1.4"
  }
}
```

**Module UI Loading:**
1. Module declares `ui = true` in manifest.
2. Module declares `[frontend]` with `script` and optional `styles` (resource
   specs pointing to packaged static assets).
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
disable flips the enabled flag, while E-STOP actively cancels framework module
runs and asks module-specific stop hooks to shut work down immediately.

## Toolforge Model

The webservice can update module registry rows and generate Jobs YAML, but
Toolforge still runs jobs from `jobs.yaml` in the tool account. The intended
flow is:

1. Edit module cron settings in the web UI.
2. Generate the new Jobs YAML from the framework.
3. Put that generated YAML into the tool's `jobs.yaml`.
4. Run `toolforge jobs load jobs.yaml`.

Cron intervals should be human-readable in manifests and UI fields, for example
`every 24 hours`, `every 15 minutes`, or `daily at 03:00`.

## Local Development

Install dependencies, then validate and test:

```bash
# Lint
npm run lint
python3 -m pylint router modules tests

# Test
python3 -m pytest -q
npm run test

# Build
npm run build
```

**For module package development:**
1. Clone the module repo next to this repo.
2. Install it editable into the framework virtualenv:

   ```bash
   python -m pip install -e ../module4awardhelper
   python scripts/check-module-install.py
   ```

3. Build the module frontend in the module repo when frontend assets change
   (e.g., `npm run build`). The framework serves packaged static assets; it does
   not import module Vue source directly.
4. Run framework and module tests from whichever repo owns the behavior you
   changed.

For the lowest-setup framework-bundled Pywikibot module, scaffold a headless
handler directly:

```bash
python scripts/create_pywikibot_module.py example_bot --enable
# Or add --schedule "every hour" for a cron handler.
```

This creates `modules/example_bot/module.toml` and `jobs.py`. Put the reviewed
Pywikibot workflow in `run(ctx, payload)`; the framework supplies OAuth,
configuration, logging, cancellation, timeout, concurrency, and run tracking.

When the module behavior is ready to deploy, commit it in the module repo, then
refresh `vendor/modules/<module_name>/` in this repo. You can pull from a local
clone while iterating:

```bash
git subtree pull \
  --prefix=vendor/modules/four_award \
  ../module4awardhelper \
  main \
  --squash
```

Use the GitHub URL and a tag for the final shared release snapshot. Toolforge
deploys the framework repo snapshot; it does not fetch module code separately.

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

For 4Award changes developed directly in the vendored framework copy, use the
checked backport helper before pushing to the module repo:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
```

The helper splits only `vendor/modules/four_award` and refuses commits that
contain framework paths. The same workflow is available as VS Code tasks.

## Documentation

Start with [Deployment-docs/DEPLOYMENT_DOCS_INDEX.md](Deployment-docs/DEPLOYMENT_DOCS_INDEX.md).
Module-specific docs should be packaged by the module and exposed through its
manifest `frontend.docs` field.
