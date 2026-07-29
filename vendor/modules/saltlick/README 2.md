# Saltlick

Saltlick is Chuckbot's guided Pywikibot workshop. It turns a page source and a
chain of text transformations into:

- a real dry run against live wiki text,
- bounded unified diffs for every proposed edit,
- a separately permissioned live run, and
- fork-ready `recipe.json`, `jobs.py`, and `module.toml` source.

The goal is practical: a Wikimedia contributor who understands the edit they
want to make should be able to get a solid Pywikibot workflow running in under
two hours without first rebuilding authentication, scheduling, permissions,
logging, cancellation, run history, or dry-run reporting.

Saltlick is a standalone Python package and Chuckbot module. The Chuckbot
framework vendors a known-good snapshot and enables it by default; day-to-day
Saltlick development can happen in its own repository.

## The under-two-hour path

1. Open **Modules → Saltlick** in Chuckbot.
2. Choose a wiki and one of the page sources.
3. Add one or more transformations.
4. Run a dry preview and inspect each diff.
5. Iterate until the report is clean.
6. Either run live with the `apply_changes` right or download the recipe and
   fork Saltlick.

Drafts remain in the browser. They are not stored as shared framework config,
and another Saltlick user cannot overwrite them.

## Page sources

Saltlick supports bounded versions of common Pywikibot generators:

- explicit page titles,
- category members, including recursive subcategories,
- backlinks or template transclusions,
- pages linked from another page,
- MediaWiki search,
- a user's contributions,
- recent changes, and
- pages with a title prefix.

Namespaces and page limits are part of the recipe, so a broad source does not
silently turn into an unbounded job.

## Transformations

Transformations run in order:

- literal find/replace,
- regex substitution with `i`, `m`, `s`, and `x` flags,
- prepend or append,
- replace the whole page,
- page templates using `{{text}}`, `{{title}}`, and `{{namespace}}`, and
- restricted expressions.

The expression language resembles a Python expression but is interpreted
node-by-node. It exposes `text`, `title`, and `namespace`, plus:

```text
replace, regex, strip, lstrip, rstrip, lower, upper, titlecase,
contains, starts_with, ends_with, length, slice
```

For example:

```python
regex(r"(?i)old name", "New name", text) if contains(lower(text), "old name") else text
```

Imports, attributes, comprehensions, arbitrary function calls, and statements
are rejected. A fork can replace the generated handler with normal Python when
the shared-host expression language is no longer enough.

## Dry-run boundary

The `preview` job always runs dry, regardless of request payload. It reads the
same pages and runs the same transformation chain as a live job, but it never
calls `page.save()`. Proposed edits and summaries are returned as
`dry_run_edits`, which the framework's normal run report renders.

Live runs have three independent gates:

1. the manifest's `apply` job requires `module:saltlick:apply_changes`;
2. the browser requires an explicit confirmation;
3. the handler requires `confirm_live=true`.

`CHUCKBOT_LOCAL_SAFE_MODE` still wins: the framework injects `dry_run=true`
into module config, which forces even the `apply` handler back to preview mode.

Diffs are bounded per page and per run. Sources, page size, transformation
count, expression size, and edit count are bounded as well. Regexes are more
permissive by design; the framework's isolated process timeout remains the
backstop for an unexpectedly expensive pattern.

Saltlick does **not** execute arbitrary user-provided Python on the shared host.
That would expose framework credentials and host data, not merely trade a small
amount of safety for features.

## API boundary

Saltlick's authoring API is mounted at `/api/v1/modules/saltlick`. The
`validate`, `preview`, and `apply` routes accept a declarative `recipe`, never
Python source or a handler path:

```json
{
  "recipe": {
    "wiki": {"code": "commons", "family": "commons"},
    "source": {"type": "category", "target": "Category:Example", "limit": 25},
    "transforms": [{"type": "literal_replace", "find": "old", "replace": "new"}],
    "save": {"summary": "Example Saltlick update"},
    "limits": {"max_edits": 25}
  },
  "inputs": {},
  "arguments": {}
}
```

The package handler is fixed by `module.toml` as
`saltlick.service:run_saltlick`. The run payload is stored as audited job data
and interpreted by that reviewed handler.

Generated bots go one step further: their recipe is baked into `jobs.py`, so
their normal run endpoint accepts only `inputs`, `arguments`, and the live
confirmation. The allowed invocation fields are deliberately small:

- inputs: `titles`, `target`;
- arguments: `source_limit`, `namespaces`, `max_edits`, `title_regex`,
  `contains`, `not_contains`, `summary`, `throttle_seconds`.

The framework supplies the fixed generated-bot routes:

```text
POST /api/v1/modules/<module-name>/jobs/preview/runs
POST /api/v1/modules/<module-name>/jobs/apply/runs
```

For example:

```json
{
  "inputs": {"target": "Category:Example"},
  "arguments": {"source_limit": 50, "max_edits": 10},
  "confirm_live": true
}
```

`confirm_live` is omitted for previews and required for apply runs.
Unknown request fields are rejected. `jobs.py` returned by `validate` is an
export artifact and is never accepted back by a run endpoint.

## Run as a standalone CLI

Install the package in a normal Pywikibot environment:

```bash
python -m pip install -e .
saltlick examples/replace-example.json
```

The default is always a dry run. A live run requires both flags:

```bash
saltlick examples/replace-example.json --live --yes
```

Pywikibot supplies the normal `user-config.py` and login behavior outside
Chuckbot.

## Develop beside Chuckbot

```bash
python -m pip install -e ../saltlick
python scripts/check-module-install.py
```

The package advertises the `saltlick` manifest through the
`chuck_buckbot.modules` entry-point group. Before a framework deploy, refresh
the vendored snapshot and keep these entries:

```text
# requirements-modules.txt
./vendor/modules/saltlick

# enabled-modules.txt
saltlick
```

The frontend source lives in `modules/saltlick/frontend`. Build the standalone
package with `npm run build`. Saltlick packages its compiled JavaScript and CSS,
and the framework serves those authenticated module assets directly; a fork
does not need a matching import in the framework's combined Vite bundle.

## Test

```bash
PYTHONPATH=modules python -m pytest -q
npm run build
```
