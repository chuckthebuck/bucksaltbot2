# Chuck the File Changer

Chuck the File Changer is a Chuck the Buckbot Framework module for large-scale,
non-visual file page text changes. It is inspired by VisualFileChange workflows,
but it works from explicit batches and Quarry result sets instead of a visual
selection interface.

Current capabilities:

- Import file titles from manual text, Quarry JSON, CSV, TSV, or VFC-style
  source discovery.
- Normalize common Quarry columns such as `img_name`, `page_title`, `file_title`,
  `actor_name`, and `user`.
- Resolve VisualFileChange-style source modes through the Commons API:
  uploader uploads, category files, page/gallery images, and file search.
- Preview exact page-text changes before saving.
- Apply exact find/replace, prepend, or append changes with Pywikibot.
- Render edit-summary variables such as `%FULLPAGENAME%`, `%FULLPAGENAMEE%`,
  `%PAGENAME%`, and `%SUMMARY_HINT%`.
- Enforce module authz for preview and live apply endpoints.
- Submit work through module-owned job and item tables with shared Celery
  workers and Redis progress snapshots.
- Scope all wiki edits to Wikimedia Commons with a module-specific user-agent.

The module is intentionally standalone. Install it into a framework checkout in
editable mode while developing:

```bash
python -m pip install -e vendor/modules/chuck_file_changer
```

Then enable `chuck_file_changer` in the framework when you are ready to wire it
into a deploy.

## Authz

`module.toml` declares `manage`, `run_jobs`, `edit_config`, and `apply_changes`.
The framework also generates `view` and `estop`.

Grant `module:chuck_file_changer:view` for UI access and
`module:chuck_file_changer:apply_changes` for live edits. Preview endpoints
require module access; applying changes requires `apply_changes` or `manage`.

## Worker

The module UI queues preview and apply runs through `chuck_file_change_jobs`
and `chuck_file_change_job_items`. Large target sets are split into chunks, each
chunk gets its own job row, and Celery runs `buckbot.process_chuck_file_change_job`
for every queued chunk. Redis stores best-effort progress snapshots under
`chuck_file_changer:job:<id>`.

## VFC Parity

The UI follows the loaded VisualFileChange source workflow for target discovery:
manual lists, Quarry lists, uploader uploads, category files, page/gallery
images, and file search all become explicit queued file-page targets before any
edit runs.

The module deliberately does not execute arbitrary user-provided Pywikibot code
from the browser. Special workflows, such as redirecting undermaintained species
galleries to categories, should be added as reviewed module actions or
registered backend functions so they can share authz, dry-run previews, edit
summaries, job rows, Redis progress, and Celery retry behavior.

## Commons Scope And User-Agent

The module is scoped to `commons.wikimedia.org`; the wiki client uses
`pywikibot.Site("commons", "commons")` and does not accept per-job wiki
overrides.

The default User-Agent includes the module release version from package
metadata. Set `CHUCK_FILE_CHANGER_USER_AGENT` to override the full identity
string for a deployment.
