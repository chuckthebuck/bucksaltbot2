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

## Module Contract

Modules are vendored package snapshots, not runtime-loaded plugins. The deploy
pins known-good framework code plus known-good module code together.

Python modules live under `vendor/modules/<module_name>/`, are installed by
local paths in `requirements-modules.txt`, and are registered only when their
module name appears in `enabled-modules.txt`:

```txt
# requirements-modules.txt
./vendor/modules/four_award

# enabled-modules.txt
rollback
four_award
```

The framework discovers and loads modules through:

1. **Vendored packages** — Modules expose an entry point in the
   `chuck_buckbot.modules` group and are listed in `enabled-modules.txt`
   (production model).
2. **Development discovery** — A `module.toml` or `module.json` file discovered
   under any subdirectory (local development model).

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
ui = true
rights = ["manage", "view_jobs", "run_jobs", "edit_config"]

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
- `ui` — Boolean; if true, module must declare `[frontend]`.
- `jobs` — List of cron jobs. Each job needs `name`, `run` (human-readable or
  cron), and either `handler` (Python function) or `endpoint` (HTTP).
- `run` — Accepts `every 24 hours`, `every 15 minutes`, `daily at 03:00`, etc.
- `rights` — Module-defined right names; become atoms like
  `module:four_award:view_jobs`.

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
- Module rights use atoms like `module:four_award:view_jobs`.
- Modules declare their own right names; the framework decides how those rights
  are granted.

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
1. Build the module frontend in the module repo (e.g., `npm run build`).
2. Include the generated static assets in the Python package.
3. The framework imports and serves packaged assets; it does not import module
   Vue source directly.
4. Test the module with `pytest tests/test_module_name.py` in the module repo.

## Documentation

Start with [Deployment-docs/DEPLOYMENT_DOCS_INDEX.md](Deployment-docs/DEPLOYMENT_DOCS_INDEX.md).
Module-specific docs should be packaged by the module and exposed through its
manifest `frontend.docs` field.
