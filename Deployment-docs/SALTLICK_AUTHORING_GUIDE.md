# Saltlick Authoring Guide

A Saltlick is one immutable, contract-driven workflow inside **Chuck the Salt
Shack**. Salt Shack generates its form and review UI from the Saltlick's YAML
contract, while the Saltlick's Python function produces structured outputs and
an optional declarative action plan. The browser never supplies Python source
or a handler path.

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

Each directory needs an entrypoint such as:

```text
category_report/
├── __init__.py
├── saltlick.yaml
└── script.py
```

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

Salt Shack also accepts smaller `run(ctx, inputs)`, `run(inputs, arguments)`,
`run(inputs)`, and `run()` signatures, but the three-argument form is clearest
and gives long-running work a cancellation boundary. Return every declared
output with the declared type; the framework validates it before saving or
rendering the result.

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

## Build, test, and publish

From the Salt Shack repository:

```bash
python3 -m pip install -e .
npm install
PYTHONPATH=modules python3 -m chuck_salt_shack.build
PYTHONPATH=modules python3 -m chuck_salt_shack.build --check
PYTHONPATH=modules python3 -m pytest -q
npm run build
```

The first build command updates the checked-in generated registry. Commit it
with the Saltlick source and contract. The `--check` command must pass before
review or deployment.

When working from this framework's vendored snapshot, run the equivalent check:

```bash
PYTHONPATH=vendor/modules/chuck_salt_shack/modules \
  python3 -m chuck_salt_shack.build --check
python3 -m pytest -q vendor/modules/chuck_salt_shack/tests
```

Then backport the reviewed subtree to the standalone repository:

```bash
bash scripts/backport-chuck-salt-shack-subtree.sh --dry-run
```

## Pre-review checklist

- The directory and all contract identifiers are lowercase snake_case.
- Inputs have useful labels, bounded numeric/page limits, and safe defaults.
- The script checks cancellation in long loops and returns only declared
  outputs.
- Read-only workflows use `actions.allowed: []`.
- Mutation workflows declare only supported actions and produce deterministic
  preview plans.
- The generated registry was rebuilt and checked in.
- Module and framework tests pass.
