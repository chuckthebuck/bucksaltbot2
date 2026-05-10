# Chuck the Buckbot Framework Access Control

Access control now mirrors the way MediaWiki user rights are usually reasoned
about:

1. Users belong to groups.
2. Groups provide rights.
3. Automatic roles can place users into groups.
4. Tool maintainers sit above the rollback-control system.

There should not be separate pages that grant the same capability through
different lists. The runtime config UI should treat groups as the normal editing
surface and show derived rights as explanation.

## Inputs

### Maintainers

Tool maintainers, including configured bot-admin accounts, receive full
framework control. They can manage rollback work, module controls, runtime
access config, and user groups.

### Role Auto Grants

Stored in `ROLE_GRANTS_JSON`.

This maps implicit roles to groups:

```json
{
  "commons_admin": ["group:basic"],
  "commons_rollbacker": ["group:basic"]
}
```

Supported auto-grant roles:

- `authenticated`
- `commons_admin`
- `commons_rollbacker`

### Rollback Control

Stored in `ROLLBACK_CONTROL_JSON`.

This maps usernames to groups:

```json
{
  "alice": ["group:rollbacker", "group:batch_runner"],
  "bob": ["group:read_only"],
  "carol": ["group:jobs_moderator"]
}
```

Direct rights may still be accepted as a migration escape hatch, but groups are
the normal interface.

## Groups

| Group | Meaning |
|---|---|
| `basic` | Can submit and manage own rollback queue jobs. |
| `read_only` | Can only view own jobs. |
| `tester` | Can use rollback tools with tester rate limits and no cross-user moderation. |
| `viewer` | Can view all jobs. |
| `rollbacker` | Can use diff and account rollback tools. |
| `rollbacker_dry_run` | Can use diff/account rollback tools, forced to dry-run mode. |
| `batch_runner` | Can submit batch rollback jobs. |
| `jobs_moderator` | Can approve jobs and cancel/retry regular users' jobs. |
| `config_editor` | Can edit runtime access configuration. |
| `rights_manager` | Can manage rollback-control groups for users. |
| `module_operator` | Can manage modules, module config, and module jobs. |
| `admin` | Broad rollback, jobs, config, and module rights. |

## Migration

Legacy runtime/env keys are read as migration input only:

| Legacy key | New equivalent |
|---|---|
| `EXTRA_AUTHORIZED_USERS` | `group:basic` |
| `USERS_READ_ONLY` | `group:read_only` |
| `USERS_TESTER` | `group:tester` |
| `USERS_GRANTED_FROM_DIFF` | `group:rollbacker` |
| `USERS_GRANTED_VIEW_ALL` | `group:viewer` |
| `USERS_GRANTED_BATCH` | `group:batch_runner` |
| `USERS_GRANTED_CANCEL_ANY` | direct `cancel_any` migration right |
| `USERS_GRANTED_RETRY_ANY` | direct `retry_any` migration right |
| `USER_GRANTS_JSON` | `ROLLBACK_CONTROL_JSON` |
| `AUTO_GRANTS_JSON` | `ROLE_GRANTS_JSON` |

New UI and API writes should use `ROLLBACK_CONTROL_JSON` and
`ROLE_GRANTS_JSON`.
