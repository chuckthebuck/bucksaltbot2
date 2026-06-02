# Vendored Subtree

This directory is the initial development repository for `chuck_file_changer`.

- Source repo: `git@github.com:chuckthebuck/Chuckthefilechange.git`
- Module version: 0.1.1
- Framework module name: `chuck_file_changer`
- Python distribution: `chuck-file-changer`
- Python import package: `chuck_file_changer`
- Framework wiring: intentionally not added yet
- Authz: module-local rights are declared in `module.toml`; no framework authz
  code changes are required because the framework supports dynamic
  `module:<module>:<right>` grant atoms.
- Autoversioning: `.github/workflows/release.yml` bumps the module patch
  version, tags `vX.Y.Z`, and creates a GitHub release on pushes to `main`.
- Push task: run `npm run modules:push:chuck-file-changer:dry-run` to inspect
  the subtree split, then `npm run modules:push:chuck-file-changer` to push the
  vendored module contents back to the source repo.
