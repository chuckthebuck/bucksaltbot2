# Vendored Module Snapshot

This directory is a vendored snapshot of the 4Award module repo.

- Source repo: `https://github.com/chuckthebuck/module4awardhelper`
- Snapshot commit: `b777437`
- Module version: `0.1.2`
- Framework module name: `four_award`
- Python distribution: `chuck-the-4awardhelper`
- Python import package: `chuck_the_4awardhelper`

This is not a live checkout of the module repo. It is the framework's pinned
deploy copy. For active development, install a local clone of the module repo in
editable mode from the framework virtualenv:

```bash
python -m pip install -e ../module4awardhelper
python scripts/check-module-install.py
```

When you are ready to update the deploy snapshot, run `git subtree pull` from
the framework repo root. During local iteration the source can be a local clone:

```bash
git subtree pull \
  --prefix=vendor/modules/four_award \
  ../module4awardhelper \
  main \
  --squash
```

For a reproducible shared release, pull from GitHub by tag:

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
