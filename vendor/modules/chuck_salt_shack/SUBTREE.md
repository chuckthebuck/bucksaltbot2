# Framework vendoring

- Source repository: <https://github.com/chuckthebuck/chuck-the-salt-shack>
- Framework integration: default-enabled package snapshot

Chuckbot vendors this standalone repository as
`vendor/modules/chuck_salt_shack`. That directory is the vendored snapshot/prefix;
its contents map directly to the standalone repository root. Files outside the
prefix belong to the framework integration and are not part of a standalone
Salt Shack backport.

The vendored snapshot includes authored source plus generated registry/frontend
artifacts required by the package. Regenerate those artifacts through the
documented build commands rather than editing them by hand, then run the
standalone test suite before using the framework's checked clone-overlay backport
helper. The helper clones the target branch, overlays only this prefix, checks the
resulting diff, and creates a normal standalone commit; it does not run a Git
subtree split.
