# Four Award Helper Module

4Award is a scheduled Buckbot module that conservatively reviews nominations on
English Wikipedia's `Wikipedia:Four Award` page. This repository-shaped
snapshot is a self-contained package for the
[Buckbot Framework](https://github.com/chuckthebuck/bucksaltbot2).

The framework loads its `chuck_buckbot.modules` entry point, serves its UI at
`/modules/four_award/ui`, and currently schedules `four-award-sync` every 15
minutes through Toolforge.

Supported production execution goes through the manifest handler and
`module_runner`. An older unprefixed Blueprint is still compatibility-mounted at
`GET /four_award/api/v1/four_award/cron/run`; it is unauthenticated, synchronous,
and bypasses framework run tracking and runtime-config injection. Do not use or
expose that endpoint as a scheduler. It should be removed once compatibility is
no longer required.

## Behavior

- Parse the records table into a local SQL-backed model.
- Rebuild records in canonical username/date order with one wikitable entry per
  line.
- Use parsed records for duplicate checks.
- Verify creation, DYK, GA, and FA evidence from relevant revisions.
- Use hidden reply markers to avoid duplicate nomination replies.
- Return ambiguous judgments as `manual_review_needed`; automated approval
  requires clear evidence and an explicit opt-in.
- Include proposed edits and a full records-table preview in dry-run output.

## Safety and configuration

Framework runtime module config is applied at the start of a managed run and
overrides the package's `FOUR_AWARD_*` environment defaults. Prefer the module
config UI for operational flags.

Keep `dry_run` true for rollout. Live behavior is separated into replies,
records, nomination removal, talk notices, and article-history switches. Enable
them one at a time in that order only after reviewing dry-run output.
`allow_automated_approval` defaults false and should remain an independent
decision.

For standalone/compatibility runs, the equivalent environment defaults include:

```text
FOUR_AWARD_DRY_RUN=1
FOUR_AWARD_ENABLE_REPLIES=1
FOUR_AWARD_ENABLE_RECORDS=1
FOUR_AWARD_ENABLE_REMOVAL=1
FOUR_AWARD_ENABLE_TALK_NOTICES=1
FOUR_AWARD_ENABLE_ARTICLE_HISTORY=1
FOUR_AWARD_ALLOW_AUTOMATED_APPROVAL=0
```

The default User-Agent includes the module version. Set
`FOUR_AWARD_HTTP_USER_AGENT` only to replace the full module identity; it is
intentionally separate from `BUCKBOT_HTTP_USER_AGENT`.

## Development and tests

Install a standalone checkout editable into the framework environment for
Python development. The module can still build its packaged static artifact
from its own root:

```bash
npm install
npm run build
```

The current framework manifest uses `bundled = true`, however, so the deployed
UI is compiled by the root Vite build from the path in
`module-frontend-packages.json` (currently the vendored source). An editable
Python install or sibling static build does not redirect that import; refresh
the snapshot or use a temporary sibling-source registry path for local-only UI
iteration.

Run the complete module-owned Python suite rather than a stale selected-file or
pylint command:

```bash
PYTHONPATH=.:modules python3 -m pytest -q tests
```

Replay fixtures compare in-memory proposed edits with known after-revisions and
never save to Wikipedia:

```bash
PYTHONPATH=. python3 -m modules.four_award.replay \
  tests/fixtures/four_award_replay_case.example.json
```

When preparing a framework deploy, refresh the committed snapshots from a clean
framework checkout with `npm run modules:update`. The current updater reads
4Award from `framework-dev` unless `FOUR_AWARD_REMOTE` or
`FOUR_AWARD_BRANCH` is deliberately overridden.

If a small integration change was developed in the vendored framework copy
first, preview the module-only backport:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
```

The helper uses a checked subtree split and refuses known framework paths. It is
an outbound backport mechanism, not the normal inbound snapshot update.
