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

Preferred flow: make module changes in the module repo, tag or commit them
there, then pull the snapshot into the framework repo.

When a 4Award change is easier to develop inside the framework first, use the
backport helper before pushing anything to the module repo:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
```

That script runs `git subtree split --prefix=vendor/modules/four_award` and
refuses the split if framework paths such as `router/`, `Deployment-docs/`,
`vendor/`, or `requirements.txt` appear in the module commit. The matching VS
Code tasks are:

- `4Award: Preview vendored subtree backport`
- `4Award: Push vendored subtree to module repo`
- `4Award: Sync vendored subtree to local clone`
