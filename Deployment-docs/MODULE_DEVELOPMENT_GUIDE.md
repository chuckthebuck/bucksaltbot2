# Module Development Guide

Chuck the Buckbot Framework modules are Python packages with validated
manifests. The framework provides login, shared config storage, Redis/SQL
access, Toolforge job orchestration, generated Jobs YAML, module permissions,
and emergency stops. The module provides its own bot logic and, when needed,
its own browser UI.

The repo split is intentionally boring:

```text
framework repo changes independently
module repo changes independently
deploy pins known-good versions together
```

Do not hand-copy module code into framework subdirectories for production.
Vendor module repos as subtree snapshots under `vendor/modules/<module_name>/`,
install those local paths during build, then register their manifests during
deploy/startup.

Framework files that matter:

- `vendor/modules/<module_name>/` contains vendored module snapshots.
- `requirements-modules.txt` installs local vendored module package paths.
- `enabled-modules.txt` lists module names to register.
- `module-frontend-packages.json` lists optional static frontend package imports
  for the Node/Vite build.

## Package Shape

Recommended package layout:

```text
module-repo/
├── pyproject.toml
├── package_name/
│   ├── __init__.py
│   ├── manifest.py
│   ├── service.py
│   ├── static/
│   │   ├── module-app.js
│   │   └── style.css
│   └── docs/
│       └── module.md
└── modules/
    └── module_name/
        └── module.toml
```

The package should expose an entry point in `pyproject.toml`:

```toml
[project.entry-points."chuck_buckbot.modules"]
four_award = "chuck_the_4awardhelper.manifest:module_manifest"
```

The entry point can return a manifest dictionary, a path to a manifest file, or
a `ModuleDefinition`.

Install the vendored module into the framework with a local path:

```txt
# requirements-modules.txt
./vendor/modules/four_award
```

Enable it by module manifest name:

```txt
# enabled-modules.txt
four_award
```

`requirements.txt` already includes `-r requirements-modules.txt`, so Toolforge
builds install the vendored Python module package with the framework. Toolforge
does not fetch module repos during build.

## Manifest

Module names must be lowercase `snake_case`. Python entry points and handlers
must be dotted import paths, not filenames.

```toml
name = "four_award"
title = "Chuck the 4awardhelper"
repo = "https://github.com/example/chuck-the-4awardhelper"
entry_point = "chuck_the_4awardhelper.service:run_four_award_sync"
ui = true
rights = ["manage", "view_jobs", "run_jobs", "edit_config", "estop"]

[[jobs]]
name = "four-award-sync"
run = "every 24 hours"
handler = "chuck_the_4awardhelper.service:run_four_award_sync"
execution_mode = "handler"
concurrency_policy = "forbid"
timeout_seconds = 600
enabled = true

[frontend]
script = "chuck_the_4awardhelper:static/four-award-app.js"
styles = ["chuck_the_4awardhelper:static/style.css"]
props_id = "four-award-props"
mount_id = "app"
docs = "chuck_the_4awardhelper:docs/four_award.md"
```

Important fields:

- `ui = true` means the module has a web surface.
- `frontend` points to packaged static assets owned by the module package.
- `jobs` are Toolforge cron-style jobs generated into `jobs.yaml`.
- `run` accepts human-readable schedules such as `every hour`, `every 15 minutes`, `every 24 hours`, or `daily at 03:00`.
- `rights` are module-defined right names. The framework grants them as atoms such as `module:four_award:view_jobs`.

## Module Frontend

Module Vue/TypeScript source should live in the module repo. Build it into
package static assets and include those assets in the Python package.

At runtime, the framework serves `/modules/<module>/ui` and loads the packaged
script and styles declared in `[frontend]`. The page includes props as JSON in
the element named by `props_id`.

Provided props:

- `username`
- `module`
- `can_manage`
- `can_run`
- `can_view_jobs`
- `can_edit_config`

Module-specific menus, preview pages, and configuration widgets belong in this
module-owned frontend. Framework screens should stay generic.

If a module also publishes a normal npm package for shared Vue/client code, pin
it in framework `package.json` and add a static import to
`module-frontend-packages.json`:

```json
{
  "modules": [
    {
      "name": "four_award",
      "import": "@chuckbot/4award/client"
    }
  ]
}
```

`npm run build` runs `scripts/generate-module-frontend-registry.mjs` before
Vite. That generates `client-src/moduleRegistry.generated.ts` with static imports
only. It is not a runtime module loader.

## Runtime Config

Non-secret module config is stored by the framework in ToolsDB and exposed via:

- `GET /api/v1/modules/<module>/config`
- `PUT /api/v1/modules/<module>/config`

Secrets and hostnames should remain environment variables where Toolforge
requires them. Module UI should write only non-secret settings.

## Jobs

A module job handler receives the module context and a payload:

```python
def run_four_award_sync(ctx, payload):
    config = ctx.config
    site = ctx.site("en", "wikipedia")
    return {"ok": True, "dry_run": bool(config.get("dry_run", True))}
```

Toolforge jobs are generated from registry rows. After editing cron schedules in
the web UI, regenerate Jobs YAML and run:

```bash
toolforge jobs load jobs.yaml
```

## Permissions

Common module rights:

- `view_jobs` — see module job runs and output.
- `run_jobs` — queue module test/manual jobs.
- `edit_config` — edit non-secret module settings.
- `manage` — manage module state and access.
- `estop` — emergency stop the module.

The module declares the vocabulary. The framework controls how users receive the
rights through maintainers, runtime groups, and MediaWiki role auto grants.

## Emergency Stop

Disable and E-STOP are different:

- Disable changes the module enabled flag and prevents future normal runs.
- E-STOP disables the module, cancels active framework module runs, and calls
  module-specific stop hooks when present.

Use E-STOP when the bot needs to stop now.
