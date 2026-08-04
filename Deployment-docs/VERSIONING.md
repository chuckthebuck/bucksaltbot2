# Versioning and Vendored Snapshots

Chuckbot versions the framework, each standalone module, and the final deploy
bundle separately. A framework tag alone identifies the exact bundle because
the module source is committed inside that framework revision.

## Framework version

The framework uses SemVer (`MAJOR.MINOR.PATCH`). Read the current value from
`VERSION`; the same value must appear in `package.json`, the root entry of
`package-lock.json`, and the lockfile's root package record. The version tests
enforce that equality.

Use:

- `MAJOR` for an incompatible deployment, database, manifest, permission, or
  public API contract.
- `MINOR` for backward-compatible framework capabilities.
- `PATCH` for fixes, documentation, scripts, tests, and compatible deployment
  changes.

Framework tags use `framework-v<version>`. The historical first release of the
current vendored-module model was `framework-v4.0.0`; it is not the current
version instruction.

`.github/workflows/release.yml` owns release bumps. It runs nightly and may be
started manually. The nightly run skips when `main` has no commit after the
latest `framework-v*` tag. Otherwise it runs
`scripts/bump-framework-version.py`, commits all three version files, tags the
commit, pushes it, and creates a GitHub release. Manual dispatch may select a
patch, minor, or major bump.

Do not hand-create a framework tag while that workflow is expected to own the
release.

## Standalone module versions

Each standalone module owns its `pyproject.toml` version and `v<version>` tags.
Modules that also have a `package.json` keep its version equal to the Python
package version; `tests/test_versioning.py` checks the vendored copies.

The release workflows currently vendored with 4Award, File Changer, and Salt
Shack bump their patch version after a normal push to `main`/`master`, commit
`chore(release): v<version>`, create the tag, and publish a GitHub release. The
workflow ignores its own release commit to avoid a loop. A module can remain
`0.x` while its operator/config contract is still evolving.

## What a vendored snapshot is

Deployable external modules live at:

```text
vendor/modules/<module_name>/
```

They are complete, repository-shaped source copies installed through
`requirements-modules.txt`. They are not submodules, editable installs, or
runtime downloads. Toolforge never fetches a module repository while building
the framework.

The current refresh mechanism is `scripts/update-vendored-modules.sh`, exposed
as:

```bash
npm run modules:update
```

The script requires a clean worktree. It shallow-clones the configured branch
for each external module, uses `rsync --delete` to overlay the corresponding
vendored root, runs `npm install`, and regenerates the bundled frontend import
registry. Its checked defaults are:

| Module | Source branch | Overrides |
| --- | --- | --- |
| 4Award | `framework-dev` | `FOUR_AWARD_REMOTE`, `FOUR_AWARD_BRANCH` |
| File Changer | `main` | `CHUCK_FILE_CHANGER_REMOTE`, `CHUCK_FILE_CHANGER_BRANCH` |
| Salt Shack | `main` | `CHUCK_SALT_SHACK_REMOTE`, `CHUCK_SALT_SHACK_BRANCH` |

The weekly `.github/workflows/update-vendored-modules.yml` runs the same command
and opens a review PR. It does not deploy the result automatically.

After refresh:

1. Review every changed file and the module package version.
2. Update `SUBTREE.md` when its recorded provenance or version is stale.
3. Run the module-owned tests and the framework canary.
4. Commit the vendored diff with the framework change that consumes it.

Do not describe these directories as live subtree links. Some backport helpers
use `git subtree split`, but the normal inbound update is the clone-and-overlay
script above.

## Backporting framework-first module edits

Prefer editing a sibling module checkout installed with `pip install -e`. When
an integration change is made in a vendored directory first, commit the
reviewed framework snapshot before backporting it.

4Award and File Changer use checked subtree-split previews:

```bash
bash scripts/backport-four-award-subtree.sh --dry-run
bash scripts/backport-chuck-file-changer-subtree.sh --dry-run
```

Those helpers split only their module prefix and refuse a result containing
known framework paths. Their non-dry-run mode pushes the split commit to the
configured module branch.

Salt Shack uses a different checked backport because a full-history subtree
split is too expensive:

```bash
bash scripts/backport-chuck-salt-shack-subtree.sh --dry-run
```

It refuses uncommitted Salt Shack files, clones the configured target branch,
overlays only `vendor/modules/chuck_salt_shack`, and shows the staged diff. The
non-dry-run command creates and pushes one Salt Shack-only commit.

## Deploy bundle identity and rollback

A deployed bundle is one framework commit/tag plus the module versions and
source files stored under `vendor/modules` in that commit. Record the framework
tag and module versions in release or incident notes.

Rollback by redeploying a known-good framework commit. For a single module
regression, revert the vendored refresh commit, run the canary, and redeploy the
new framework commit. A runtime disable or E-STOP is an incident-control action,
not a substitute for restoring a known-good source bundle.
