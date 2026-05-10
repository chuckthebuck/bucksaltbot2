# Vendored Module Snapshot

This directory is a vendored snapshot of the 4Award module repo.

- Source repo: `https://github.com/chuckthebuck/module4awardhelper`
- Snapshot commit: `b777437`
- Module version: `0.1.2`
- Framework module name: `four_award`
- Python distribution: `chuck-the-4awardhelper`
- Python import package: `chuck_the_4awardhelper`

Update this directory with `git subtree pull` from the framework repo root:

```bash
git subtree pull \
  --prefix=vendor/modules/four_award \
  https://github.com/chuckthebuck/module4awardhelper.git \
  v0.1.2 \
  --squash
```

Do not casually hand-edit files in this directory. Make module changes in the
module repo, tag or commit them there, then pull the snapshot into the framework
repo.
