# Salt Shack

Salt Shack is Chuckbot's default, contract-driven Pywikibot module. The module
contains any number of independently runnable **Saltlicks**. Each immediate
subdirectory under `modules/saltlick/saltlicks/` becomes one nested UI and one
fixed server-side script.

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
modules/saltlick/saltlicks/
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
the standard wiki and raw Pywikibot-argument controls. Add a contract when the
script should receive typed inputs or return structured output.

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

Page values are normalized into an explicit API shape:

```json
{
  "wiki": {"code": "commons", "family": "commons"},
  "namespace": 10,
  "title": "Example"
}
```

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

For small scripts Salt Shack also accepts:

```text
run(ctx, inputs)
run(inputs, arguments)
run(inputs)
run()
```

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
framework-owned action catalog. Salt Shack does not contain the MediaWiki
mutation implementation.

Preview runs validate and display the action plan without executing it. The
result includes a SHA-256 plan digest. Apply runs regenerate the plan and must
match the reviewed digest before the framework executes any action.

The first shipped framework action is:

```text
mediawiki.page.purge
```

Additional non-editing MediaWiki actions can be added to the framework catalog
without changing the Saltlick UI renderer.

## API

```text
GET  /api/v1/modules/saltlick/saltlicks
GET  /api/v1/modules/saltlick/saltlicks/<saltlick-id>
GET  /api/v1/modules/saltlick/saltlicks/<saltlick-id>/runs
POST /api/v1/modules/saltlick/saltlicks/<saltlick-id>/runs
GET  /api/v1/modules/saltlick/runs/<run-id>
```

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

## Generated registry

Build the self-generated YAML registry:

```bash
PYTHONPATH=modules python3 -m saltlick.build
```

Verify that the checked-in/generated artifact matches the directories:

```bash
PYTHONPATH=modules python3 -m saltlick.build --check
```

`npm run build` runs the registry compiler before the Codex frontend build.
The generated artifact is packaged into the image for review and deployment
audits. Runtime discovery uses the same compiler rules.

## Develop and test

```bash
python3 -m pip install -e .
npm install
npm run typecheck
npm run build
PYTHONPATH=modules python3 -m pytest -q
```

When vendored into Chuckbot:

```bash
PYTHONPATH=vendor/modules/saltlick/modules \
  python3 -m pytest -q vendor/modules/saltlick/tests

python3 -m pytest -q tests/test_saltlick_module.py tests/test_wiki_actions.py
npm run build
```

## Deployment

Salt Shack remains a separate, forkable repository while Chuckbot vendors a
known-good snapshot under `vendor/modules/saltlick`.

Production wiring remains:

```text
requirements-modules.txt: ./vendor/modules/saltlick
enabled-modules.txt:      saltlick
```

The manifest's compatibility key remains `saltlick`; its user-facing title is
**Salt Shack**.
