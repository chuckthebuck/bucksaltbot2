# Chuck the File Changer

Chuck the File Changer is a Chuck the Buckbot Framework module for large-scale,
non-visual file page text changes. It is inspired by VisualFileChange workflows,
but it works from explicit batches and Quarry result sets instead of a visual
selection interface.

Current capabilities:

- Import file titles from manual text, Quarry JSON, CSV, or TSV.
- Normalize common Quarry columns such as `img_name`, `page_title`, `file_title`,
  `actor_name`, and `user`.
- Preview exact page-text changes before saving.
- Apply exact find/replace, prepend, or append changes with Pywikibot.
- Enforce module authz for preview and live apply endpoints.
- Submit work through the framework module job queue and shared Celery worker.
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

The manifest declares one framework worker job, `file-change`, under
`worker_jobs`. It is intentionally not a Toolforge cron job. The module UI
queues preview and apply runs through `module_job_runs`, and the shared Celery
task `buckbot.process_module_job_run` executes the module handler on the same
worker system used by rollback.

## Commons Scope And User-Agent

The module is scoped to `commons.wikimedia.org`; the wiki client uses
`pywikibot.Site("commons", "commons")` and does not accept per-job wiki
overrides.

The default User-Agent includes the module release version from package
metadata. Set `CHUCK_FILE_CHANGER_USER_AGENT` to override the full identity
string for a deployment.
