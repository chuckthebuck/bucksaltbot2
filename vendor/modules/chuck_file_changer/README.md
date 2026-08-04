# Chuck the File Changer

Chuck the File Changer is the Commons-scoped Buckbot module for reviewed,
non-visual file-page text changes. It turns explicit target batches, Quarry
results, or VisualFileChange-style source discovery into durable preview/apply
jobs.

Current capabilities:

- Parse manual text, JSON, CSV, and TSV target lists.
- Accept Quarry query/run IDs or URLs and normalize common title columns.
- Discover uploader uploads, category files, page/gallery images, and file
  search results through the Commons API.
- Plan exact replace, regex replace, prepend, and append operations.
- Render `%FULLPAGENAME%`, `%FULLPAGENAMEE%`, `%PAGENAME%`, and
  `%SUMMARY_HINT%` in edit summaries.
- Force preview requests to dry-run and authorize apply requests separately.
- Queue work in module-owned job/item tables and expose Redis progress.

The framework currently enables and installs the committed snapshot under
`vendor/modules/chuck_file_changer`. For day-to-day standalone development,
clone the source repository separately and install that checkout editable into
the framework virtualenv. Refresh the deploy snapshot only after review:

```bash
npm run modules:update
```

## Authorization and routes

The manifest declares `manage`, `run_jobs`, `edit_config`, and
`apply_changes`; the framework generates `view` and `estop`.

- Preview/source endpoints require authenticated module access.
- Apply requires configured `module:chuck_file_changer:apply_changes`,
  `module:chuck_file_changer:manage`, or the global `manage_modules` override.
  Framework maintainer status alone is not folded into this custom route check.
- Job status is visible to its requester; configured module/global managers can
  inspect other users' File Changer jobs. The generic shell's `can_manage` hint
  can therefore be broader than the custom API's answer for a maintainer.

The current compatibility Blueprint is mounted at
`/chuck_file_changer/api/...`, including `auth`, `targets/parse`, `quarry/url`,
`preview`, `apply`, and `jobs/<id>`. It has not moved to the generic
`/api/v1/modules` namespace.

## Queue and safety model

Preview and apply submissions are independent jobs; apply does not reuse a
browser-held preview result. The preview route overwrites request flags to stay
read-only. The custom queue receives no framework runtime context, so only the
request payload's `dry_run=true` can downgrade an apply submission; ToolsDB
runtime config and `CHUCKBOT_LOCAL_SAFE_MODE` are not injected.

Targets are split into module-owned `chuck_file_change_jobs` and
`chuck_file_change_job_items` rows. Keep `chunk_size` at or below 100. The API
currently clamps requests as high as 500, but the queue worker invokes the
service without a framework context and therefore processes only the first 100
items before marking that chunk complete; larger values leave remaining item
rows queued. Celery runs one task per durable chunk, and Redis keeps best-effort
snapshots under `chuck_file_changer:job:<id>`.

This queue is separate from framework `module_job_runs`. Generic module
E-STOP/disable neither cancels File Changer's queued/running rows nor blocks new
preview/apply submissions through its already-mounted Blueprint. Remove access
and follow the incident procedure—which may require stopping web/shared-worker
processes and restarting without the module—until an explicit native stop
integration exists.

## Scope and User-Agent

Wiki work is fixed to `commons.wikimedia.org`; jobs cannot select another wiki.
The default User-Agent includes the module release version. Set
`CHUCK_FILE_CHANGER_USER_AGENT` only to replace the full deployment identity.

The module intentionally does not execute arbitrary browser-provided Python.
New special workflows should be reviewed backend operations so they retain
authorization, dry-run behavior, durable jobs, progress, and bounded inputs.
