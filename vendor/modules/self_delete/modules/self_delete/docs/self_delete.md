# Commons Self Delete

This module processes narrowly defined Commons G7 requests. It is designed for
a workflow where trusted uploaders can place a file in a monitored
speedy-deletion category by adding `{{SD|G7}}` themselves. The bundled operator
page shows effective safety settings, queues protected manual test runs, and
links to recent framework output.

Before a live deletion the module requires all of the following, twice:

- the category member is a live file page;
- the current page contains `G7` inside an active `SD`, `Speedydelete`, or
  `Speedy` template (prose, other templates, and HTML comments do not count);
- the editor who introduced the current marker is the original uploader;
- every binary revision was uploaded by that same user;
- the file is strictly younger than seven days;
- neither local nor global file usage exists; and
- the uploader currently has the `autopatrol` right.

The cron job never deletes inline. It writes eligible files into
`self_delete_jobs` and `self_delete_job_items`. These dedicated tables use the
same atomic claim, worker chunking, and shared Celery infrastructure as rollback
without mixing self-delete records into rollback history. The second validation
happens in the claiming worker immediately before the delete request. A changed
or newly used file is safely completed as a no-edit skip. The module defaults to
`dry_run=true`.

Discovery is intentionally broad: it lists file members of the configured
speedy-deletion category. Each discovered file is then verified independently.
If any required fact is absent, ambiguous, or fails its check while an active G7
marker remains, a queue worker replaces that token with `G7(failed bot)`. The
`SD` template then falls through to `Speedydelete`, placing the file in
`Category:Other speedy deletions` for human review. The verification reason is
kept in SQL and in the edit summary. If the marker disappears before the worker
runs, no edit is made. Dry-run mode reports the proposed reroute without editing.

## Runtime configuration

- `enabled` (default `true`)
- `dry_run` (default `true`)
- `category_title` (default `Category:Other speedy deletions`)
- `max_age_seconds` (default and hard maximum `604800`)
- `max_candidates` (default `250`, maximum `1000`)
- `workers` (default `4`, maximum `16`)
- `deletion_reason`

The UI's **Run dry test** action re-reads persisted configuration immediately
before enqueueing and is unavailable while `dry_run=false`. It also attaches a
one-way `dry_run=true` run flag, so a later global configuration change cannot
turn queued test work live. Payloads can force protection on but cannot disable
configured dry-run protection.

## Offline testing harness

The fixture harness runs the real discovery and policy-inspection code without
SQL, network access, credentials, or a writable MediaWiki API. Its site adapter
raises immediately if code attempts a delete request:

```sh
PYTHONPATH=vendor/modules/self_delete/modules:. \
  python3 -m self_delete.harness \
  vendor/modules/self_delete/tests/fixtures/dry_run_mixed.json
```

## SQL audit trail

`self_delete_runs` stores configuration and aggregate outcomes,
`self_delete_candidates` stores the final decision and complete check snapshot,
and `self_delete_events` stores every discovery, individual policy check, queue
handoff, worker claim, revalidation, state transition, deletion attempt, and
error. Worker names and structured JSON context are included so concurrent
activity can be reconstructed. The associated `self_delete_jobs` and
`self_delete_job_items` rows are the durable work queue and operational status.
