# Granular Permissions

Buckbot access control is group-and-right based. Environment variables from the
older rollback-only model are still read as migration input, but new UI and API
writes should use runtime groups.

## Model

1. Users are mapped to groups in `ROLLBACK_CONTROL_JSON`.
2. Automatic roles can map users to groups through `ROLE_GRANTS_JSON`.
3. Groups provide framework rights.
4. Module rights are normal rights with the `module:<name>:<right>` shape.
5. Tool maintainers and bot admins sit above runtime grants.

## Runtime Groups

| Group | Typical Use |
|---|---|
| `basic` | Basic rollback queue access. |
| `read_only` | View own rollback jobs only. |
| `tester` | Tester-level rollback access with tester rate limits. |
| `viewer` | View all rollback jobs and module job runs. |
| `rollbacker` | Rollback from diff/account tools. |
| `rollbacker_dry_run` | Rollback tools forced into dry-run behavior. |
| `batch_runner` | Batch rollback jobs. |
| `jobs_moderator` | Approve, cancel, and retry regular users' jobs. |
| `config_editor` | Edit runtime access configuration. |
| `rights_manager` | Manage user/group assignments. |
| `module_operator` | Manage modules, module config, and module jobs. |
| `admin` | Broad framework and module administration. |

## Module Rights

Module manifests declare only module-owned worker/config rights, for example:

```toml
rights = ["manage", "run_jobs", "edit_config"]
```

The framework automatically provides:

- `module:<name>:view`
- `module:<name>:estop`

Do not declare those generated rights in module manifests. They are framework
surfaces and do not need worker code.

## Auto Grants

`ROLE_GRANTS_JSON` maps implicit roles to groups:

```json
{
  "authenticated": ["group:basic"],
  "commons_admin": ["group:basic"],
  "commons_rollbacker": ["group:basic"]
}
```

The exact available roles are defined by the framework auth layer. Keep grants
small and prefer groups over direct rights.

## Legacy Environment Migration

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

## Testing

Use focused tests around the permission behavior you changed:

```bash
python3 -m pytest -q tests/test_authz.py tests/test_module_registry.py
python3 -m pytest -q tests/test_router.py -k "permission or module or access"
```

If broad router tests fail because external Toolhub or Wikimedia calls are not
available in a sandbox, record that separately from real authorization failures.
