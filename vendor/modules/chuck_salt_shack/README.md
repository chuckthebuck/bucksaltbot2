# Chuck the Salt Shack

**Chuck the Salt Shack**, shown as **Salt Shack** in compact UI titles, is
Chuckbot's default contract-driven Pywikibot module. The module
contains any number of independently runnable **Saltlicks**. Each immediate
subdirectory under `modules/chuck_salt_shack/saltlicks/` becomes one nested UI and one
fixed server-side script.

Canonical repository:
<https://github.com/chuckthebuck/chuck-the-salt-shack>

The intended authoring path is deliberately short:

1. Duplicate a Saltlick directory.
2. Rename the directory.
3. Replace `script.py`.
4. Describe inputs, outputs, and allowed actions in `saltlick.yaml`.
5. Rebuild Salt Shack.

There is no runtime **Add Saltlick** endpoint. Saltlick source and contracts are
immutable image contents.

## Directory convention

```text
modules/chuck_salt_shack/saltlicks/
├── page_purger/
│   ├── saltlick.yaml
│   └── script.py
└── transclusion_report/
    ├── saltlick.yaml
    └── script.py
```

The directory name is the stable Saltlick ID. No central Python or frontend
registry needs to be edited.

If `saltlick.yaml` is omitted, the build generates a zero-config contract with
the standard wiki and raw compatibility-argument controls plus an optional JSON
`result` output. Add a contract when the script needs named or additional typed
inputs or outputs, or when it declares allowed actions.

## Contract

```yaml
contract: 1
display_name: Page purger
description: Preview and perform cache purges.
entrypoint: script.py:run

inputs:
  wiki:
    type: wiki
    required: true
    default: {code: commons, family: commons}

  targets:
    type: pages
    required: true
    max_items: 250
    namespace:
      selectable: true
      allowed: [0, 2, 4, 6, 10, 14]
      default: 0

  force_link_update:
    type: boolean
    default: true

outputs:
  planned_count:
    type: number
    label: Planned purges

  targets:
    type: pages
    label: Target pages

actions:
  allowed:
    - mediawiki.page.purge
```

Salt Shack owns the Codex layout. Contracts describe semantics only; they do
not contain HTML, Codex component names, colors, columns, or arbitrary layout.

### Input types

- `string`
- `text`
- `integer`
- `number`
- `boolean`
- `choice`
- `wiki`
- `namespace`
- `page`
- `pages`
- `user`
- `date`
- `datetime`

Page input values are normalized into an explicit namespace/title shape:

```json
{
  "namespace": 10,
  "title": "Example"
}
```

The selected wiki remains in its linked `wiki` input. A Saltlick that emits a
page action or a cross-wiki page output attaches that wiki to the page object,
as `page_purger/script.py` does. This keeps a form's project selection
normalized once while making every executable action target self-contained.

For `page` and `pages`, namespace policy can be fixed or selectable. Salt Shack
loads the selected wiki's real namespace names and uses namespace-scoped Codex
lookups for page titles. `pages` renders as a multi-select lookup with chips.

When a contract has exactly one `wiki` input, Salt Shack automatically links
all `namespace`, `page`, and `pages` inputs to it. If a Saltlick exposes
multiple wiki inputs, point a dependent input at the right one:

```yaml
inputs:
  source_wiki:
    type: wiki
  source_page:
    type: page
    wiki_input: source_wiki
```

The wiki selector is populated from Wikimedia's site matrix, with common
projects available as an offline fallback.

### Output types

- `string`
- `number`
- `boolean`
- `message`
- `page`
- `pages`
- `table`
- `json`

Tables declare typed columns. Returned output and action data are validated
against the installed contract before they are persisted as the run result.

## Script contract

The recommended function accepts the framework context, normalized inputs, and
raw compatibility arguments:

```python
def run(ctx, inputs, arguments):
    site = ctx.site(
        inputs["wiki"]["code"],
        inputs["wiki"]["family"],
    )
    return {
        "outputs": {
            "count": 0,
            "rows": [],
        },
        "actions": [],
    }
```

For small scripts Salt Shack also accepts these unambiguous abbreviated forms:

```text
run(ctx, inputs)
run(inputs)
run()
```

The `arguments` list is opaque compatibility data. Salt Shack validates its
size and string values but does not interpret it as a shell command or apply it
to Pywikibot automatically. A script that consumes it must use the unambiguous
three-argument `run(ctx, inputs, arguments)` signature; a two-argument handler
is always interpreted as `run(ctx, inputs)`.

The browser never submits a script path, handler path, or Python source. The
worker resolves the requested Saltlick ID against the compiled image registry.

## Framework actions

Scripts return declarative action envelopes:

```python
{
    "type": "mediawiki.page.purge",
    "target": {
        "wiki": {"code": "commons", "family": "commons"},
        "namespace": 0,
        "title": "Main Page",
    },
    "params": {"forcelinkupdate": True},
}
```

Action types must be declared by the Saltlick and implemented by Chuckbot's
framework-owned action catalog. Salt Shack validates the generic action
envelope—type, page target, and JSON-safe parameters—but does not contain the
MediaWiki mutation implementation.

Preview runs validate the envelope and allowlist, then display the action plan
without executing it. The result includes a SHA-256 digest over the Saltlick
ID, normalized inputs, compatibility arguments, and ordered actions. Apply runs
regenerate that data and must match the reviewed digest before the framework
executes anything. Operation-specific required parameters are enforced by the
framework executor during live dispatch, so authors should test both preview
and apply behavior on a safe target.

The current framework action catalog supports both `mediawiki.page.*` and
`pywikibot.page.*` names for:

```text
purge, edit, delete, undelete, move, protect, touch, watch, unwatch, rollback
```

The two prefixes reach the same reviewed catalog; neither permits arbitrary
method lookup. New action types can be added to that framework catalog without
changing Salt Shack's contract renderer, but a Saltlick must still declare each
type it may emit.

## API

```text
GET  /api/v1/modules/chuck_salt_shack/auth
GET  /api/v1/modules/chuck_salt_shack/saltlicks
GET  /api/v1/modules/chuck_salt_shack/saltlicks/<saltlick-id>
GET  /api/v1/modules/chuck_salt_shack/saltlicks/<saltlick-id>/runs
POST /api/v1/modules/chuck_salt_shack/saltlicks/<saltlick-id>/runs
POST /api/v1/modules/chuck_salt_shack/saltlicks/<saltlick-id>/estop
GET  /api/v1/modules/chuck_salt_shack/runs/<run-id>
```

All routes require an authenticated user with Shack-wide access or a generated
right for at least one Saltlick. Run and emergency-stop routes then enforce the
specific capability again. Run history is limited to the caller's rows unless
the caller has the Shack `manage` right.

Custom apply and per-Saltlick E-STOP checks use configured module grants
directly. A configured global `manage_modules` grant satisfies them, but fixed
framework maintainer status alone does not; grant the explicit Shack or
Saltlick capability when a maintainer must use those controls.

Preview request:

```json
{
  "mode": "preview",
  "inputs": {
    "targets": [
      {"namespace": 0, "title": "Main Page"}
    ]
  },
  "arguments": ["-verbose"]
}
```

Apply request:

```json
{
  "mode": "apply",
  "inputs": {
    "targets": [
      {"namespace": 0, "title": "Main Page"}
    ]
  },
  "arguments": ["-verbose"],
  "confirm_live": true,
  "preview_token": "<digest returned by preview>"
}
```

The emergency-stop endpoint accepts `{"enabled": false}` to stop a Saltlick
and request cancellation of its active runs, or `{"enabled": true}` to resume
it. The framework's module-wide emergency stop remains a separate control.

### Legacy recipe compatibility API

The current Codex UI is generated from installed Saltlick contracts; it does
not expose the older free-form recipe builder. Version-1 JSON recipes remain
supported for direct CLI use, existing integrations, and generating a separate
forkable module:

```text
POST /api/v1/modules/chuck_salt_shack/validate
POST /api/v1/modules/chuck_salt_shack/preview
POST /api/v1/modules/chuck_salt_shack/apply
```

These routes accept only bounded recipe data and an explicit invocation
overlay, never Python source or a handler path. `examples/replace-example.json`
is a legacy CLI/compatibility recipe, not a contract for the current nested
Saltlick UI. Run it locally in preview mode with:

```bash
PYTHONPATH=modules python3 -m chuck_salt_shack.cli \
  examples/replace-example.json
```

## Generated registry

Build the self-generated YAML registry:

```bash
PYTHONPATH=modules python3 -m chuck_salt_shack.build
```

Verify that the checked-in/generated artifact matches the directories:

```bash
PYTHONPATH=modules python3 -m chuck_salt_shack.build --check
```

`npm run build` runs the registry compiler before the Codex frontend build.
The generated artifact is packaged into the image for review and deployment
audits. Runtime discovery uses the same compiler rules. Every non-hidden source
file inside a Saltlick directory contributes to its source digest, including
script comments and YAML comments, so documentation-only Saltlick changes also
require regenerating the audit registry before release.

## Develop and test

```bash
python3 -m pip install -e .
npm install
npm run typecheck
npm run build
# The API/service tests import the framework's router package.
CHUCKBOT_FRAMEWORK_ROOT=/path/to/bucksaltbot2
PYTHONPATH="modules:$CHUCKBOT_FRAMEWORK_ROOT" python3 -m pytest -q
```

When vendored into Chuckbot:

```bash
PYTHONPATH=.:vendor/modules/chuck_salt_shack/modules \
  python3 -m pytest -q vendor/modules/chuck_salt_shack/tests

python3 -m pytest -q tests/test_chuck_salt_shack_module.py tests/test_wiki_actions.py
npm run build
```

`examples/ui-preview.html` is a hand-authored browser fixture with synthetic
API responses. It demonstrates the packaged UI; its sample run IDs and digests
are not deployment state.

## Deployment

Chuck the Salt Shack remains a separate, forkable repository while Chuckbot
vendors a known-good snapshot under `vendor/modules/chuck_salt_shack`.

Production wiring remains:

```text
requirements-modules.txt: ./vendor/modules/chuck_salt_shack
enabled-modules.txt:      chuck_salt_shack
```

The module key is `chuck_salt_shack`; `Saltlick` refers only to one child script
inside the Shack. Its concise user-facing title is **Salt Shack**, while the
formal module name is **Chuck the Salt Shack**.

## Publishing the standalone repository

The GitHub repository name is **Chuck the Salt Shack** and its URL-safe slug is
`chuck-the-salt-shack`. In a framework checkout this directory is the vendored
snapshot/prefix whose contents become the standalone repository root. Do not
include the surrounding Chuckbot framework or local `node_modules`, cache,
virtual-environment, build, or coverage directories.

When publishing changes developed in the framework checkout, first commit the
reviewed framework state and then, from the framework repository root, use its
checked clone-overlay backport helper (the script retains its historical
`subtree` filename):

```bash
bash scripts/backport-chuck-salt-shack-subtree.sh --dry-run
bash scripts/backport-chuck-salt-shack-subtree.sh
```

The first command clones the target and prints the exact Salt Shack-only diff
without committing or pushing. The second repeats the checked overlay, commits
it in the standalone clone, and pushes it to
`https://github.com/chuckthebuck/chuck-the-salt-shack.git` after the remote
repository exists.
