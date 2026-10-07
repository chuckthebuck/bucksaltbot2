# Chuck Self Delete

Chuck the Buckbot module for conservatively processing Wikimedia Commons G7
requests made by uploaders with the `autopatrol` right. It includes a bundled
operator UI, a scheduled scanner, a dedicated queue, and an offline test harness.

This directory is a deploy snapshot of the standalone `chuck-self-delete`
repository. Develop in a sibling clone, then refresh the framework snapshot with
`SELF_DELETE_REMOTE=/absolute/path/to/chuck-self-delete npm run modules:update`.
The framework commit pins the exact reviewed module contents deployed to
Toolforge; production never fetches module source at runtime.

The module defaults to dry-run mode. Its cron job discovers files through a
configured category and validates policy conditions in parallel. Eligible files
are then written to dedicated `self_delete_jobs` and `self_delete_job_items`
tables. The jobs share the framework's Celery broker and worker pool and use the
rollback queue's atomic-claim pattern without mixing their records into rollback
history. Workers repeat every check immediately before a possible live delete.

Run its focused tests from the framework root:

```sh
PYTHONPATH=vendor/modules/self_delete/modules:. \
  python3 -m pytest -q vendor/modules/self_delete/tests
```

Exercise the complete eligibility policy against a local fixture without a wiki
login, database, queue, or deletion capability:

```sh
PYTHONPATH=vendor/modules/self_delete/modules:. \
  python3 -m self_delete.harness \
  vendor/modules/self_delete/tests/fixtures/dry_run_mixed.json
```

The operator page is compiled into the framework bundle through
`module-frontend-packages.json`. Its manual button refuses to enqueue unless the
persisted module configuration has dry-run protection enabled, and its job
payload independently forces that individual run to remain dry.
