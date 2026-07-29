# Saltlick

Saltlick takes you from a repeatable wiki edit to a working Pywikibot workflow:

1. choose a wiki and a bounded page source;
2. chain text transformations;
3. filter pages and set edit limits;
4. run a dry preview against live page text;
5. inspect every proposed diff; and
6. run live or export the recipe and generated module source.

## Sources

You can start from page titles, category members, backlinks/template
transclusions, links on a page, wiki search, user contributions, recent
changes, or a title prefix. A source reads at most 500 pages. Use namespaces
and a smaller limit while developing.

## Changes

Saltlick applies every transform in order. It supports literal and regex
replacement, prepend/append, full-page templates, whole-page replacement, and
restricted expressions.

Template text can use:

- `{{text}}` — text entering this transformation;
- `{{title}}` — full page title;
- `{{namespace}}` — numeric namespace.

Expression transforms expose `text`, `title`, and `namespace`, with the safe
functions listed in the UI. They do not execute arbitrary Python. Download the
generated source and edit it in a fork when you need unrestricted code.

## Dry run and live run

Preview is structurally dry: the preview handler never calls `page.save()`.
The report includes the edit summary and bounded unified diff for every
proposed change.

A live run requires the `module:saltlick:apply_changes` right, the browser
confirmation, and the handler's live confirmation. The maximum-edit setting is
a hard ceiling. Local safe mode forces all Saltlick runs back to dry-run mode.

Start with one sandbox page, then a small representative source, then the full
bounded set.

## Forking

**Validate and generate code** produces:

- `recipe.json` — portable workflow data;
- `jobs.py` — a framework handler using Saltlick's tested engine;
- `module.toml` — a starter module manifest.

The Saltlick package is deliberately a separate, forkable module repository
even though Chuckbot includes it by default.

The shared authoring API accepts declarative `recipe`, `inputs`, and
`arguments` objects. It never accepts Python source. In generated modules, the
recipe is baked into the reviewed handler and run endpoints accept only the
documented inputs and arguments.
