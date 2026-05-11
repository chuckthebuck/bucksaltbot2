# Versioning

Chuckbot uses separate versions for the framework, module source repos, and the
deployed bundle.

## Framework Version

The framework uses SemVer:

```text
MAJOR.MINOR.PATCH
```

The first subtree-based framework release is:

```text
4.0.0
```

Increment rules:

- `MAJOR`: breaking deployment model, database contract, module manifest
  contract, permission model, or public API behavior.
- `MINOR`: backward-compatible framework features, new shared APIs, new
  framework-owned UI, or new module integration surfaces.
- `PATCH`: bug fixes, docs, scripts, tests, and compatible deployment fixes.

The framework version is stored in:

```text
VERSION
package.json
```

Tag framework releases as:

```text
framework-v4.0.0
```

Framework release tags are created by the nightly release workflow, not on every
commit to `main`. The workflow checks whether `main` has commits after the
latest `framework-v*` tag; if not, it skips the night. Maintainers can also run
the workflow manually and choose `patch`, `minor`, or `major`.

## Module Versions

Each module repo owns its own SemVer tags:

```text
v0.1.2
v0.2.0
v1.0.0
```

Modules may stay `0.x` while their config, output, or UI contract is still
moving quickly. A module `1.0.0` means the module owner considers its manifest,
config keys, and operator workflow stable.

## Vendored Module Snapshots

The framework repo vendors deployable module snapshots under:

```text
vendor/modules/<module_name>/
```

Those directories are git subtree snapshots of module repos. The framework
deploy does not fetch module repos from GitHub; Toolforge installs local module
paths from `requirements-modules.txt`.

Example:

```txt
# requirements-modules.txt
./vendor/modules/four_award
```

Update a module snapshot from the framework repo root:

```bash
git subtree pull \
  --prefix=vendor/modules/four_award \
  https://github.com/chuckthebuck/module4awardhelper.git \
  v0.1.2 \
  --squash
```

Commit message convention:

```text
vendor(four_award): update to v0.1.2
```

Each vendored module directory should include a `SUBTREE.md` file recording:

- source repo
- source commit
- module version
- framework module name
- Python distribution/import names

## Deploy Bundle Version

A deployed bundle is the framework tag plus the vendored module snapshots in
that framework commit.

Example:

```text
framework-v4.0.0
  four_award v0.1.2 at b777437
  rollback bundled framework module
```

Rollback is done by redeploying a previous framework commit or by reverting the
specific vendored module snapshot commit.

## Ownership Rule

Do not make casual edits inside `vendor/modules/<module_name>/`.

Normal flow:

```text
edit module repo
test module repo
tag module repo
git subtree pull into framework repo
run local canary
deploy framework repo
```

Emergency hotfixes inside `vendor/modules/<module_name>/` are allowed only if
they are immediately backported to the module repo and followed by a normal
subtree update.
