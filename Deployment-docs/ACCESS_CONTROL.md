# Access Control

Buckbot evaluates access from four sources. In descending order of authority:

1. `BOT_ADMIN_ACCOUNTS` and Toolhub maintainers.
2. Explicit user grants in `ROLLBACK_CONTROL_JSON`.
3. Automatic Wikimedia-role grants in `ROLE_GRANTS_JSON`.
4. Compatibility-only module access rows in the `module_access` table.

The effective configuration is assembled in `router/authz.py`; route-level
checks are in `router/permissions.py` and `router/routes.py`. Runtime values in
the `runtime_config` table override environment defaults for the current keys.

## Maintainers and protected configuration

`app.is_maintainer()` returns true for a configured bot-admin account or a
maintainer returned by Toolhub. Maintainers can manage modules and normal
rollback work. Bot admins have one additional rollback capability: they may
cancel work owned by another maintainer.

Runtime authorization configuration is intentionally more restrictive than
ordinary module administration:

- Bot admins and Toolhub maintainers may view it.
- The bot admin named by `CONFIG_EDIT_PRIMARY_ACCOUNT` (default `chuckbot`) may
  edit the whole authorization configuration.
- A user with the `edit_config` right may also edit it.
- Any bot admin, or a user with `manage_user_grants`, may edit individual user
  assignments.

Do not assume that every maintainer can change the protected authorization
document. The checks above are enforced independently by the `/api/v1/config/authz`
routes.

## Current runtime keys

| Key | Meaning |
| --- | --- |
| `ROLLBACK_CONTROL_JSON` | Maps normalized MediaWiki usernames to `group:<name>` atoms and/or direct rights. |
| `ROLE_GRANTS_JSON` | Maps implicit Wikimedia roles to groups or direct rights. |
| `CHUCKBOT_GROUPS_JSON` | Defines custom group bundles. Built-in groups are present in the effective default. |
| `CHUCKBOT_GROUP_DESCRIPTIONS_JSON` | Stores optional descriptions for custom groups. |
| `RATE_LIMIT_JOBS_PER_HOUR` | Per-user rollback submission limit; `0` disables it. |
| `RATE_LIMIT_TESTER_JOBS_PER_HOUR` | Tester-specific limit; defaults to the regular limit. |

Usernames are normalized to MediaWiki's first-letter-uppercase form and
underscores become spaces when policy is saved. There is an important current
compatibility limitation: the main `_user_permissions()` path lowercases the
entire authenticated username before direct framework-grant lookup. A stored
key such as `AlaChuckthebuck` is therefore looked up as `Alachuckthebuck` on
those routes, even though MediaWiki can treat them as distinct accounts.
Module-scoped helper checks preserve the original session spelling. Until the
legacy lowercase lookup is removed, verify effective access for mixed-case
usernames and do not rely on later-character case to isolate grants.

Example:

```json
{
  "Alice": ["group:rollbacker", "group:batch_runner"],
  "Bob": ["group:read_only"],
  "Carol": ["module:four_award:view", "module:four_award:run_jobs"]
}
```

Direct rights remain supported, but groups are easier to audit when several
users need the same capability.

## Built-in groups

| Group | Expanded rights |
| --- | --- |
| `basic` | Submit and manage the user's own basic rollback queue work. |
| `read_only` | View only the user's own rollback jobs. This group short-circuits normal rollback grants. |
| `tester` | Basic work, all-job viewing, diff/account rollback, and batch rollback. |
| `viewer` | View all rollback jobs and module runs. |
| `rollbacker` | Basic work plus diff and account rollback. |
| `rollbacker_dry_run` | Diff/account rollback with the dry-run-only restriction. |
| `batch_runner` | Basic work plus batch rollback. |
| `jobs_moderator` | Approve, force dry run, cancel, and retry regular users' jobs. |
| `config_editor` | Edit runtime authorization configuration. |
| `rights_manager` | Manage individual user grant assignments. |
| `module_operator` | Full authority over every module, including all present and future module-scoped sensitive rights such as live apply. |
| `admin` | Broad rollback, moderation, config, user-grant, and full module authority. |

Custom groups may contain framework rights or module atoms. The API rejects
unknown framework rights, while module-specific atoms are deliberately dynamic
so a module can introduce a right without changing the authorization engine.

## Automatic Wikimedia-role grants

`ROLE_GRANTS_JSON` supports these role selectors:

- `authenticated`
- `commons_admin`
- `commons_rollbacker`
- `project:<project>:<group>`, for example
  `project:enwiki:extendedconfirmed`
- `global:<group>`, for example `global:global-sysop`

Example:

```json
{
  "commons_admin": ["group:basic"],
  "project:enwiki:extendedconfirmed": ["module:four_award:view"],
  "global:global-sysop": ["group:module_operator"]
}
```

Project and global membership is fetched from Wikimedia and cached for five
minutes. Failed lookups do not invent membership.

## Module rights and access

Module atoms have this shape:

```text
module:<module_name>:<right>
```

The framework generates `view` and `estop` for every registered module. A
module manifest declares its worker/config rights, such as `manage`,
`run_jobs`, `edit_config`, or a sensitive action right such as
`apply_changes`. A job's `required_right` is checked in addition to the normal
run permission.

Salt Shack also generates three independently grantable rights for every
compiled Saltlick:

```text
module:chuck_salt_shack:saltlick_<saltlick_id>_preview
module:chuck_salt_shack:saltlick_<saltlick_id>_apply
module:chuck_salt_shack:saltlick_<saltlick_id>_estop
```

The older `module_access` table still provides a simple enter/view grant and is
edited by `PUT /api/v1/modules/<module>/access`. It does not replace
operation-specific rights. Prefer group or direct module-right grants whenever
the user needs run, config, apply, or E-STOP capabilities.

`view_all` allows broad module-run discovery on the registry and compatible
list surfaces. It is not, by itself, accepted by every module-owned or legacy
detail route. In particular, the framework-hosted
`/modules/runs/<run_id>/report` page currently requires direct module access or
`module:<name>:view`, module/global management, or maintainer status. A user who
can see a run in a list through `view_all` may therefore receive `403` when
following its report link. Grant the module's `view` right when report access is
required; use `view_jobs` only for surfaces whose route explicitly accepts it.

## Compatibility inputs

The following environment variables and persisted runtime rows are still read
so an older deployment does not lose access during upgrade:

| Compatibility key | Effective current grant |
| --- | --- |
| `EXTRA_AUTHORIZED_USERS` | `group:basic` |
| `USERS_READ_ONLY` | `group:read_only` |
| `USERS_TESTER` | `group:tester` |
| `USERS_GRANTED_FROM_DIFF` | `group:rollbacker` |
| `USERS_GRANTED_VIEW_ALL` | `group:viewer` |
| `USERS_GRANTED_BATCH` | `group:batch_runner` |
| `USERS_GRANTED_CANCEL_ANY` | direct `cancel_any` |
| `USERS_GRANTED_RETRY_ANY` | direct `retry_any` |
| `USER_GRANTS_JSON` | fallback input for `ROLLBACK_CONTROL_JSON` |
| `AUTO_GRANTS_JSON` | merged into `ROLE_GRANTS_JSON` |

Legacy atom aliases such as `group:operator`, `from_diff`, `batch`, and
`read_all` are resolved while permissions are expanded. The framework does not
delete or rewrite those old values automatically. Save current keys through the
runtime config UI/API, verify effective access, and then remove the old inputs
from the deployment.
