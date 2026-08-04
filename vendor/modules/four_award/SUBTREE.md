# Vendored Module Snapshot

This directory is the framework's committed deploy snapshot of 4Award.

- Source repo: `https://github.com/chuckthebuck/module4awardhelper`
- Source branch used by the updater: `framework-dev`
- Snapshot commit: `b777437`
- Module version: `0.1.2`
- Framework module name: `four_award`
- Python distribution: `chuck-the-4awardhelper`
- Python import package: `chuck_the_4awardhelper`

It is not a live checkout. For active work, install a sibling module clone
editable into the framework virtualenv. For the normal inbound deploy refresh,
start with a clean framework worktree and run:

```bash
npm run modules:update
```

The updater shallow-clones the configured branch and overlays this directory
with `rsync --delete`. Override `FOUR_AWARD_REMOTE` or `FOUR_AWARD_BRANCH` only
for a reviewed source, then review every replaced file and run module-owned
tests. Do not use the old `git subtree pull` instructions; they are no longer
the checked inbound workflow.

For a framework-first change, preview the outbound module-only history split:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
```

That helper runs `git subtree split --prefix=vendor/modules/four_award` and
refuses output containing known framework paths. Its non-dry-run mode pushes
the split commit to the configured module branch.
