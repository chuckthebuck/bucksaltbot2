# Ownership Map: What Changes, Where, and What Deploys

Use this map before editing or deploying. “Owned” here means the repository or
system that is the authoritative place to make the change; it does not imply
legal ownership.

| Thing | Authoritative owner | Edit it there | What does **not** update it |
| --- | --- | --- | --- |
| Deployed framework bundle | Your framework deployment repository | Framework code, `jobs.yaml`, deployment metadata, and vendored module snapshots | A local unpushed checkout, the original framework upstream, or a module-repository push |
| Module source | The module's standalone repository | Module Python, module UI, module tests, and module docs | Editing a vendored snapshot, unless you deliberately backport it |
| Module copy used by production | `vendor/modules/<module>` in the framework deployment repository | Refresh it from the reviewed module source, commit the resulting framework diff | The module source repository alone; Build Service does not clone it |
| Toolforge Build Service image | Toolforge, from the pushed framework deployment revision | Push the framework deployment commit, then run the workflow/build | Files present only on the Toolforge filesystem or in an editable local install |
| Toolforge checkout | `/data/project/<tool-name>` under the tool account | Set its `origin` to the framework deployment repository and keep the workflow path aligned | A separate clone in a subdirectory or a checkout with the old `origin` |
| Toolforge secrets and runtime identity | The new tool account's envvars and OAuth configuration | Toolforge envvars and the OAuth provider settings | `.env`, `jobs.yaml`, GitHub repository files, or module manifests |
| Live schedules | The committed framework `jobs.yaml` | Generate/review the block, commit it to the framework deployment repository, and deploy | ToolsDB rows alone or a module manifest alone |
| Persistent runtime state | ToolsDB and Redis for the selected tool namespace | Framework UI/API or approved operational commands | Git commits; deploys do not automatically migrate arbitrary runtime state |

## The deploy boundary

```text
module source repository
          │  reviewed refresh / backport
          ▼
framework deployment repository ── push ──► GitHub deploy workflow
          │                                      │
          │ checked `jobs.yaml`                  ▼
          └────────────────────────────► Toolforge Build Service image
                                                   │
                                                   ▼
                                      webservice + workers + schedules
```

Only the **framework deployment repository** is a Build Service source. Module
repositories are inputs to its vendored snapshots, not independently deployed
services. The initial name/repository setup is covered in
[RENAMING_AND_REPOSITORIES.md](RENAMING_AND_REPOSITORIES.md).

## Framework-owned versus module-owned paths

The framework owns shared infrastructure and generic behavior: Flask/OAuth,
authorization, ToolsDB/Redis integration, module discovery, generic run
tracking, generated schedules, and framework pages. Framework-owned modules
live under `modules/` (currently Rollback).

An external module owns its package behavior, UI, documentation, tests,
manifest contract, and any module-specific queue/API cleanup. Its deployable
copy lives under `vendor/modules/<module>` only so a framework revision is a
self-contained, reproducible bundle. That vendored copy is not the canonical
development home unless the team has explicitly chosen to work there and
backport afterward.

The framework owns only its generic E-STOP and module-run lifecycle. A module
with a separate queue, custom Blueprint, or external system must own and test
its additional containment behavior.
