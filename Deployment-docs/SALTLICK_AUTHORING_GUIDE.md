# Saltlick Authoring Guide

A Saltlick is one reviewed workflow directory inside **Chuck the Salt Shack**.
Salt Shack generates its form and review UI from an optional YAML contract,
while the Saltlick's Python function produces structured outputs and an
optional declarative action plan. A directory without YAML receives a minimal,
read-only default contract. The browser never supplies Python source or a
handler path.

## Create a Saltlick

Work in the standalone Salt Shack repository when possible. In this framework
checkout, the vendored source is located at:

```text
vendor/modules/chuck_salt_shack/modules/chuck_salt_shack/saltlicks/
```

Copy the closest existing example. `transclusion_report` is read-only;
`page_purger` plans framework-owned write actions.

```bash
cd vendor/modules/chuck_salt_shack/modules/chuck_salt_shack/saltlicks
cp -R transclusion_report category_report
```

Use a lowercase, snake_case directory name. It becomes the stable Saltlick ID
and must start with a letter. Do not add it through the browser or edit a
central frontend registry.

The recommended directory has an explicit contract:

```text
category_report/
├── __init__.py
├── saltlick.yaml
└── script.py
```

Only the Python entrypoint is required. With no `saltlick.yaml` or
`saltlick.yml`, discovery expects `script.py:run`, adds one Commons `wiki`
input, exposes one optional JSON result, and allows no actions. Use that
zero-config shape only for small read-only tools; add YAML as soon as the
workflow needs typed fields, named outputs, or framework actions. A directory
must not contain both YAML filename variants.

## Define the contract

`saltlick.yaml` is user-facing input/output metadata plus a bounded execution
contract. It is not a place for HTML, component names, arbitrary Python
methods, or unreviewed action types.

```yaml
contract: 1
display_name: Category report
description: List a bounded set of pages in a category.
entrypoint: script.py:run

inputs:
  wiki:
    type: wiki
    label: Wiki
    required: true
    default: {code: commons, family: commons}

  category:
    type: page
    label: Category
    required: true
    namespace:
      selectable: false
      allowed: [14]
      default: 14

  limit:
    type: integer
    label: Maximum pages
    default: 100
    minimum: 1
    maximum: 500

outputs:
  count:
    type: number
    label: Matching pages
  pages:
    type: pages
    label: Pages

actions:
  allowed: []
```

Supported input types are `string`, `text`, `integer`, `number`, `boolean`,
`choice`, `wiki`, `namespace`, `page`, `pages`, `user`, `date`, and `datetime`.
Supported output types are `string`, `number`, `boolean`, `message`, `page`,
`pages`, `table`, and `json`.

With exactly one `wiki` input, page and namespace inputs automatically use that
wiki. For multiple wiki inputs, add `wiki_input: source_wiki` to each dependent
page or namespace field. `pages` fields can set `max_items`; keep limits small
enough for a user to review.

## Write the script

The preferred entrypoint accepts the framework context, normalized inputs, and
raw compatibility arguments:

```python
from typing import Any


def run(ctx: Any, inputs: dict, arguments: list[str]) -> dict:
    del arguments
    wiki = inputs["wiki"]
    site = ctx.site(wiki["code"], wiki["family"])

    # Use bounded Pywikibot iteration. Check cancellation inside long loops.
    pages = []
    for page in some_bounded_iterator(site, limit=inputs["limit"]):
        ctx.check_cancelled()
        pages.append(
            {
                "wiki": wiki,
                "namespace": int(page.namespace()),
                "title": str(page.title()),
            }
        )

    return {"outputs": {"count": len(pages), "pages": pages}, "actions": []}
```

Salt Shack also accepts smaller `run(ctx, inputs)`, `run(inputs)`, and `run()`
signatures, but the three-argument form is clearest and gives long-running work
a cancellation boundary. A two-argument function is always interpreted as
`(ctx, inputs)`; consume compatibility `arguments` only through the
three-argument form. Return every declared output with the declared type; the
framework validates it before saving or rendering the result.

## Plan actions, do not execute them directly

For wiki changes, return declarative action envelopes rather than calling a
mutating Pywikibot method in the Saltlick. Add every action type to
`actions.allowed` and return only those types.

```python
return {
    "outputs": {"planned_count": len(targets), "targets": targets},
    "actions": [
        {
            "type": "mediawiki.page.purge",
            "target": target,
            "params": {"forcelinkupdate": True},
        }
        for target in targets
    ],
}
```

The framework currently supports the `mediawiki.page.*` and
`pywikibot.page.*` variants of `purge`, `edit`, `delete`, `undelete`, `move`,
`protect`, `touch`, `watch`, `unwatch`, and `rollback`. The exact parameters
are validated by [router/wiki_actions.py](../router/wiki_actions.py). Preview
runs only validate and show this plan. Apply runs regenerate it and require the
same preview digest, so make the plan deterministic for the same inputs.

## Rights, runs, and emergency stops

The module manifest declares broad `manage`, `run_jobs`, and `apply_changes`
rights. Salt Shack also generates these rights from every discovered directory:

```text
module:chuck_salt_shack:saltlick_<id>_preview
module:chuck_salt_shack:saltlick_<id>_apply
module:chuck_salt_shack:saltlick_<id>_estop
```

Broad Shack rights remain valid, while the generated atoms let an operator
grant one workflow without granting every Saltlick. The current per-Saltlick
API surface is:

```text
GET  /api/v1/modules/chuck_salt_shack/saltlicks
GET  /api/v1/modules/chuck_salt_shack/saltlicks/<id>
POST /api/v1/modules/chuck_salt_shack/saltlicks/<id>/runs
GET  /api/v1/modules/chuck_salt_shack/saltlicks/<id>/runs
POST /api/v1/modules/chuck_salt_shack/saltlicks/<id>/estop
```

The run endpoint accepts `mode: preview` or `mode: apply`. Apply also requires
`confirm_live: true` and the `preview_token` returned by a matching preview.
The per-Saltlick E-STOP persists that Saltlick as disabled and requests
cancellation only for its active runs; it does not stop other Saltlicks.

## Build, test, and publish

From the Salt Shack repository:

```bash
python3 -m pip install -e .
npm install
PYTHONPATH=modules python3 -m chuck_salt_shack.build
PYTHONPATH=modules python3 -m chuck_salt_shack.build --check
# Full API/service tests also import the Chuckbot framework's router package.
CHUCKBOT_FRAMEWORK_ROOT=/path/to/bucksaltbot2
PYTHONPATH="modules:$CHUCKBOT_FRAMEWORK_ROOT" python3 -m pytest -q
npm run build
```

The first build command updates the checked-in generated registry. Commit it
with the Saltlick source and contract. Runtime discovery still reads the
packaged child directories; the generated YAML is the deterministic build and
image-audit snapshot. The `--check` command must pass before review or
deployment.

When working from this framework's vendored snapshot, run the equivalent check:

```bash
PYTHONPATH=vendor/modules/chuck_salt_shack/modules \
  python3 -m chuck_salt_shack.build --check
PYTHONPATH=.:vendor/modules/chuck_salt_shack/modules \
  python3 -m pytest -q vendor/modules/chuck_salt_shack/tests
```

Then preview the reviewed Salt Shack-only backport to the standalone repository:

```bash
bash scripts/backport-chuck-salt-shack-subtree.sh --dry-run
```

## Pre-review checklist

- The directory and all contract identifiers are lowercase snake_case.
- Inputs have useful labels, bounded numeric/page limits, and safe defaults.
- The script checks cancellation in long loops and returns only declared
  outputs.
- Read-only workflows use `actions.allowed: []`.
- Zero-config workflows remain read-only and return only the default optional
  JSON result.
- Mutation workflows declare only supported actions and produce deterministic
  preview plans.
- The generated registry was rebuilt and checked in.
- Module and framework tests pass.
