# Four Award Helper Module

Cron-backed Buckbot module for conservatively reviewing and processing [[Wikipedia:Four Award]] nominations on English Wikipedia.

This repository is a self-contained module package for the [Buckbot Framework](https://github.com/chuckthebuck/bucksaltbot2/tree/main/5).

## Module Structure

- `pyproject.toml` — Package metadata with Buckbot entry point
- `modules/four_award/module.toml` — Module manifest (name, cron jobs, UI, docs)
- `modules/four_award/service.py` — Cron job handler entry points
- `modules/four_award/frontend/` — Vue app source
- `modules/four_award/static/` — Built Vue app (committed to git)
- `modules/four_award/docs/four_award.md` — User-facing documentation

The framework loads this module by entry point at startup and serves the UI at `/modules/four_award/ui`.

## Safety model

The module has per-action switches plus one emergency stop. To force a non-writing run, set:

```bash
FOUR_AWARD_DRY_RUN=1
```

Live action flags:

```bash
FOUR_AWARD_DRY_RUN=0
FOUR_AWARD_ENABLE_REPLIES=1
FOUR_AWARD_ENABLE_RECORDS=1
FOUR_AWARD_ENABLE_REMOVAL=1
FOUR_AWARD_ENABLE_TALK_NOTICES=1
FOUR_AWARD_ENABLE_ARTICLE_HISTORY=1
```

HTTP identity:

```bash
FOUR_AWARD_HTTP_USER_AGENT="FourAwardHelper/0.1 (https://github.com/chuckthebuck/module4awardhelper; User:Alachuckthebuck)"
```

This is intentionally separate from `BUCKBOT_HTTP_USER_AGENT`, so the framework
and each module can identify their own Wikimedia API traffic independently.

Recommended rollout:

1. Run dry-run only.
2. Enable nomination replies while keeping records/removal disabled.
3. Enable records after verifying table rebuilds.
4. Enable nomination removal, talk notices, and article-history updates last.

## Behavior

* Records table rows are parsed into a local SQL-backed model before rendering.
* Records table rows are rebuilt in canonical order: username A-Z, then award date/time.
* Each wikitable entry is emitted as a single line.
* Dry-run output includes a full records-table preview when approved records
  would be added.
* Duplicate nomination checks use the parsed records table rather than a raw
  substring search.
* The bot replies to nominations with hidden markers to avoid duplicate replies.
* Ambiguous judgment calls become `manual_review_needed`; the bot only approves with clear evidence and only fails on objective problems.
* Creation is checked against the article's first MediaWiki revision plus early article edits.
* DYK, GA, and FA credit is checked against process-page revisions/signatures and article edits during the relevant milestone windows.
* Automated approval is disabled unless `FOUR_AWARD_ALLOW_AUTOMATED_APPROVAL=1`.

## Development

### Building the Frontend

```bash
npm install
npm run build
```

The built app is written to `modules/four_award/static/` and committed to git. The Buckbot Framework reads it from there.

### Testing and Linting

In this repo:
```bash
PYTHONPATH=. python -m py_compile modules/four_award/*.py
```

Linting, type checking, and full module tests run in the framework repo context:
```bash
# In bucksaltbot2/5/
python3 -m pylint modules.four_award
npm run lint
python3 -m pytest tests/test_module_registry.py
```

Focused module tests from this repository:

```bash
PYTHONPATH=. python3 -m pytest -q tests/test_four_award_records.py tests/test_four_award_replay.py
```

### Developing Inside the Framework

The framework vendors this repo under `vendor/modules/four_award`. If you make a
small 4Award change there while working on framework integration, preview the
subtree split before pushing it back to the module repo:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
```

The matching VS Code task is `4Award: Preview vendored subtree backport`.
Use `4Award: Push vendored subtree to module repo` only after the dry-run shows
module files only. The script refuses splits that contain framework paths such
as `router/`, `Deployment-docs/`, `vendor/`, or `requirements.txt`.

## Historic replay tests

Replay cases compare the bot's in-memory edits against known after-revisions, without saving to Wikipedia:

```bash
PYTHONPATH=. python -m modules.four_award.replay tests/fixtures/four_award_replay_case.example.json
```

Use `before_revid` and `expected_revid` for each page touched by an old review diff. Add `page_creation` and `revision_users` evidence so the reviewer can reproduce the old approval/failure decision deterministically.
