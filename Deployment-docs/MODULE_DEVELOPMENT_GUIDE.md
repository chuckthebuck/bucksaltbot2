# Module Development Guide

Chuck the Buckbot Framework modules are Python packages with validated
manifests. The framework provides login, shared config storage, Redis/SQL
access, Toolforge job orchestration, generated Jobs YAML, module permissions,
and emergency stops. The module provides its own bot logic and, when needed,
its own browser UI.

The repo split is intentionally boring for deploys:

```text
framework repo changes independently
module repo changes independently
deploy pins known-good versions together
```

That does not mean every edit has to go through GitHub and a vendored refresh.
For normal development, work in the module repo directly and install it into the
framework virtualenv in editable mode. Vendor module repos as
repository-shaped snapshots under `vendor/modules/<module_name>/` only for
deployable framework commits.

Framework files that matter:

- `vendor/modules/<module_name>/` contains vendored module snapshots.
- `requirements-modules.txt` installs local vendored module package paths.
- `enabled-modules.txt` lists module names to register.
- `module-frontend-packages.json` lists optional static frontend package imports
  for the Node/Vite build.

## Development vs Deploy

There are three supported module modes:

| Mode | Where code lives | How framework sees it | When to use it |
| --- | --- | --- | --- |
| Framework-bundled | `modules/<module_name>/` | manifest discovery under `modules/` | rollback and other framework-owned modules |
| Editable package | separate local module repo | Python entry point from `pip install -e` | day-to-day module development |
| Vendored snapshot | `vendor/modules/<module_name>/` | Python entry point from `requirements-modules.txt` | Toolforge deploys and reproducible bundles |

Chuck the Salt Shack is the reference for the last two modes. It is enabled in
the default framework build but kept as a complete repository-shaped package under
`vendor/modules/chuck_salt_shack/`, so contributors can fork it or install a sibling
clone editable without moving its implementation into the framework.

Its canonical upstream is `https://github.com/chuckthebuck/chuck-the-salt-shack`. When
Salt Shack changes are first developed in the framework snapshot, commit the
framework work and backport only the module directory to that repository:

```bash
bash scripts/backport-chuck-salt-shack-subtree.sh --dry-run
bash scripts/backport-chuck-salt-shack-subtree.sh
```

The helper accepts `CHUCK_SALT_SHACK_REMOTE` and
`CHUCK_SALT_SHACK_BRANCH` overrides for a local bootstrap repository, fork, or
release branch. The upstream repository must exist before the non-dry-run push.

Use editable packages while building. Use vendored snapshots when you need a
single framework commit that Toolforge can build without fetching another repo.

For 4Award development from the framework repo:

```bash
# one-time setup, assuming the module repo is next to this repo
.venv/bin/python -m pip install -e ../module4awardhelper
.venv/bin/python scripts/check-module-install.py
```

The editable install exposes the same `chuck_buckbot.modules` entry point as
the vendored package. Python code changes in the module repo are picked up
without copying files into `vendor/`; restart the local web/job process if the
imported module is already loaded.

Frontend code follows the manifest's assembly mode. With `bundled = false`,
build the sibling module so its packaged static assets are updated and served
through the authenticated module-asset route. With `bundled = true`, the root
Vite build imports the path in `module-frontend-packages.json`; the checked
4Award and File Changer entries point into `vendor/`, so an editable Python
install does not expose sibling Vue changes. Refresh the vendored snapshot or
temporarily point that registry entry at sibling source for local iteration,
run the root build, and do not commit a developer-specific path.

When you are ready to deploy, commit the module repo and refresh the framework's
vendored snapshots with the checked repository command:

```bash
npm run modules:update
```

`scripts/update-vendored-modules.sh` refuses a dirty worktree, clones the
configured source branches into temporary directories, overlays only the three
vendored module roots, runs `npm install`, and regenerates the static frontend
registry. Its defaults currently use 4Award's `framework-dev` branch and the
`main` branches for File Changer and Salt Shack. Override the corresponding
`*_REMOTE` and `*_BRANCH` variables for a reviewed fork or release branch.

Review the complete vendored diff, run module-owned tests, and update the
module's `SUBTREE.md` provenance when its recorded version or source revision
changes. Toolforge builds the committed copy; it does not consult the upstream
module branch during deployment.

## Package Shape

Recommended package layout:

```text
module-repo/
├── pyproject.toml
└── modules/
    └── module_name/
        ├── __init__.py
        ├── manifest.py
        ├── service.py
        ├── module.toml
        ├── static/
        │   ├── module-app.js
        │   └── style.css
        └── docs/
            └── module.md
```

The package should expose an entry point in `pyproject.toml`:

```toml
[project.entry-points."chuck_buckbot.modules"]
four_award = "chuck_the_4awardhelper.manifest:module_manifest"
```

The entry point can return a manifest dictionary, a path to a manifest file, or
a `ModuleDefinition`. Keep `module.toml` as the source of truth; the small
Python entry point should load that packaged file rather than duplicate its
contents:

```python
from importlib.resources import files
import tomllib

def module_manifest():
    text = files(__package__).joinpath("module.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)
```

Include `module.toml` in the package-data section of `pyproject.toml`.

Install the vendored module into the framework with a local path for production
builds:

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
does not fetch module repos during build. Editable installs are for local
development only and should not be committed to `requirements-modules.txt`.

## Manifest

Module names must be lowercase `snake_case`. Python entry points and handlers
must be dotted import paths, not filenames.

```toml
name = "four_award"
title = "4awardhelper"
repo = "https://github.com/example/chuck-the-4awardhelper"
entry_point = "chuck_the_4awardhelper.service:run_four_award_sync"
blueprint_entry_point = "chuck_the_4awardhelper.blueprint:blueprint"
ui = true
rights = ["manage", "run_jobs", "edit_config"]

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

- `ui = true` means the module has a web surface. It does not by itself require
  a `[frontend]` section.
- `frontend` points to packaged static assets owned by the module package and,
  when present, requires `ui = true`.
- `blueprint_entry_point` is optional and separate from the job handler entry
  point. Headless Pywikibot modules can omit it.
- `jobs` are Toolforge cron-style jobs generated into `jobs.yaml`.
- `worker_jobs` are controller-run jobs that can be queued manually without a
  cron schedule.
- `run` accepts human-readable schedules such as `every hour`, `every 15 minutes`, `every 24 hours`, or `daily at 03:00`.
- `concurrency_policy` is `forbid` by default; `replace` cancels older active
  runs and `allow` permits overlap.
- `required_right` adds a job-specific module right on top of `run_jobs`; use it
  for sensitive handlers such as live wiki edits. The right must also be
  declared in the module-level `rights` list.
- `rights` are module-defined worker right names. The framework grants them as
  atoms such as `module:four_award:run_jobs`. The framework automatically
  provides `module:<name>:view` and `module:<name>:estop`, so modules should not
  declare those rights.
- `execution_mode = "handler"` and `execution_mode = "k8s_job"` currently
  generate the same isolated `module_runner` Toolforge command. The bundled
  template uses `handler`; `http` is the protected endpoint-backed
  compatibility mode.

## CTB API Namespace

The framework owns the CTB API namespace. In this codebase the current route
prefix is `/api/v1`:

```txt
/api/v1/modules
/api/v1/modules/<module>/config
/api/v1/modules/<module>/jobs
/api/v1/modules/<module>/estop
```

Those standard routes are generated from the module registry and shared
framework controllers. Module-owned CTB APIs may also live in this namespace,
but they should stay under their module path:

```txt
/api/v1/modules/<module>/<module-owned-resource>
```

Avoid adding new top-level module API paths such as `/api/v1/four-award/...`.
Those should move under `/api/v1/modules/four_award/` over time. A module
manifest should not need to declare the generated framework endpoint paths. If a
module needs to describe external API behavior, such as Wikimedia API URL,
user-agent, or edit-summary tag, keep that separate from CTB routes.

A module Blueprint can own its module namespace by declaring its Flask
`url_prefix`, for example
`Blueprint("chuck_salt_shack", __name__, url_prefix="/api/v1/modules/chuck_salt_shack")`.
Blueprints without an explicit prefix retain the compatibility mount at
`/<module_name>`.

## Module Frontend

Module Vue/TypeScript source should live in the module repo. Whether the runtime
uses packaged static assets or the framework's combined Vite bundle is selected
by `frontend.bundled`.

At runtime, the framework serves `/modules/<module>/ui`. The page includes props
as JSON in the element named by `props_id`; it either loads declared package
assets or relies on the module entry already compiled into the root bundle.

Every enabled, accessible module with a frontend is also added to the Modules
subnav from its manifest. Do not add module names to `templates/base.html`.

There are two supported frontend assembly modes:

- `bundled = true` imports the module's Vue entry through
  `module-frontend-packages.json` into the framework Vite build.
- `bundled = false` serves the module's compiled JavaScript and CSS directly
  through the authenticated `/module-assets/<module>/...` route. This is the
  recommended mode for a separately forkable module such as Chuck the Salt
  Shack.

Provided props:

- `username`
- `module`
- `can_manage`
- `can_run`
- `can_view_jobs`
- `can_edit_config`

Module-specific menus, preview pages, and configuration widgets belong in this
module-owned frontend. Framework screens should stay generic.

For a bundled module frontend, add its actual source entry to
`module-frontend-packages.json`. The current 4Award entry is:

```json
{
  "modules": [
    {
      "name": "four_award",
      "enabled": true,
      "import": "../vendor/modules/four_award/modules/four_award/frontend/entry.ts"
    }
  ]
}
```

`npm run build` runs `scripts/generate-module-frontend-registry.mjs` before
Vite. That generates `client-src/moduleRegistry.generated.ts` with static imports
only for `bundled = true` entries. It is not the module subnav registry and it
is not a runtime module loader.

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

Handlers may accept `()`, `(ctx)`, `(payload)`, or `(ctx, payload)`. The
two-argument form is recommended. `ctx.config` is a read-only mapping,
`ctx.check_cancelled()` provides cooperative cancellation, and
`ctx.site(code, family)` returns a logged-in Pywikibot site using the
framework-managed credentials.

A manually queued handler can be declared without a schedule:

```toml
rights = ["run_jobs", "apply_changes"]

[[worker_jobs]]
name = "apply-changes"
handler = "example_module.service:apply_changes"
timeout_seconds = 900
concurrency_policy = "forbid"
required_right = "apply_changes"
```

The generic run API accepts handler payload data but rejects
`config_overrides`. Persistent configuration must go through the module config
API, where the framework applies the module's config-edit permission.

Generic manual runs are first persisted as `queued` rows. The continuous
`buckbot-module-controller` process claims them and starts `module_runner` as a
separate child process with the manifest timeout and cooperative cancellation.
Some module-owned APIs dispatch a named Celery task immediately instead; that
task atomically claims the same row so only one execution owner can win.

For a separate OAuth identity, set `oauth_consumer_mode = "module"` and declare
the source environment-variable names:

```toml
oauth_consumer_key_env = "EXAMPLE_CONSUMER_TOKEN"
oauth_consumer_secret_env = "EXAMPLE_CONSUMER_SECRET"
oauth_access_token_env = "EXAMPLE_ACCESS_TOKEN"
oauth_access_secret_env = "EXAMPLE_ACCESS_SECRET"
```

The isolated runner maps those four values into Pywikibot only for that module
process. The manifest contains variable names, never credential values.

Toolforge jobs are generated from registry rows. After editing cron schedules in
the web UI, regenerate the marked module block in `jobs.yaml`, review and
commit it, then deploy. The deploy wrapper flushes current Toolforge jobs and
loads the committed file. For an intentional exact jobs-only reconciliation
from the tool checkout, accept a brief interruption to continuous jobs and run:

```bash
toolforge jobs flush
toolforge jobs load jobs.yaml
```

`load` alone can add/update definitions but does not guarantee that a removed or
renamed job disappears.

Handler jobs are the default. Compatibility `execution_mode = "http"` jobs
require an application-path `endpoint` plus deploy-time
`MODULE_CRON_BASE_URL` and secret `MODULE_CRON_TOKEN`; their public trigger
rejects requests without that token.

That protection applies to the framework-generated compatibility trigger, not
arbitrary module Blueprint routes. 4Award currently retains an unsupported
legacy `GET /four_award/api/v1/four_award/cron/run` route with no token, run
tracking, or runtime-config injection. Do not copy or schedule that pattern.

## Permissions

Common module rights:

- `view` — see module UI, job runs, and output; generated by the framework.
- `estop` — emergency stop the module; generated by the framework.
- `run_jobs` — queue module test/manual jobs.
- `edit_config` — edit non-secret module settings.
- `manage` — manage module state and access.

Salt Shack additionally generates `saltlick_<id>_preview`,
`saltlick_<id>_apply`, and `saltlick_<id>_estop` rights for each discovered
Saltlick. Those suffixes are still stored in the normal
`module:chuck_salt_shack:<right>` atom shape.

The module declares only the worker-facing vocabulary. The framework controls
how users receive both module-declared and framework-generated rights through
maintainers, runtime groups, and MediaWiki role auto grants.

## Emergency Stop

Disable and E-STOP are different:

- Disable changes the registry flag. The generic run API and `module_runner`
  reject a disabled module, but an already registered custom Blueprint remains
  mounted until web restart and must enforce its own state.
- E-STOP disables the module, requests cancellation for active
  `module_job_runs`, and attempts to delete its scheduled Toolforge jobs/pods.
  Rollback also cancels rollback rows and purges the configured Buckbot Celery
  queue. That queue is shared, so the purge can discard queued Salt Shack or
  File Changer task messages as well. A module that owns a separate queue/table
  must implement and wire its own cleanup; there is no generic stop-hook call
  today.

Use E-STOP only after identifying which execution owner and queue must stop. A
custom Blueprint may remain mounted until web restart, and a module-owned queue
may require its own incident control or coordinated web/worker shutdown.
