# Vendored Module Snapshot

This directory is the framework's committed deploy snapshot of Chuck the File
Changer. It is not the initial development repo, a live subtree link, or an
unwired package.

- Source repo: `git@github.com:chuckthebuck/Chuckthefilechange.git`
- Source branch used by the updater: `main`
- Module version: `0.1.1`
- Framework module name: `chuck_file_changer`
- Python distribution: `chuck-file-changer`
- Python import package: `chuck_file_changer`
- Framework wiring: installed by `requirements-modules.txt`, enabled by
  `enabled-modules.txt`, and bundled into the framework frontend build.
- Autoversioning: the module release workflow bumps patch, tags `vX.Y.Z`, and
  creates a GitHub release on normal pushes to `main`.

Normal inbound refresh is the framework clone-and-overlay updater:

```bash
npm run modules:update
```

It requires a clean worktree. Override `CHUCK_FILE_CHANGER_REMOTE` or
`CHUCK_FILE_CHANGER_BRANCH` only for a reviewed fork/revision, then review the
complete replaced snapshot and run module-owned tests.

If a change was developed in this snapshot first, preview the checked
File-Changer-only split before publishing it upstream:

```bash
bash scripts/backport-chuck-file-changer-subtree.sh --dry-run
```

The non-dry-run helper pushes the `git subtree split` result to the configured
branch after refusing known framework paths. Backport splitting is not the
inbound refresh mechanism.
