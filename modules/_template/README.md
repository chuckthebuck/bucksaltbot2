# Framework-Bundled Module Template

This template is for modules that intentionally live inside the framework repo,
such as rollback. Most new production modules should instead be separate Python
packages with a `chuck_buckbot.modules` entry point, installed editable during
development and vendored under `vendor/modules/<module>/` for deploy.

## Use This Template For Built-In Modules

1. Copy this directory to `modules/<module_name>/`.
2. Update `module.toml` with the module name and job metadata.
3. Put the custom Pywikibot workflow in `jobs.py`.
4. Add the module name to `enabled-modules.txt`.
5. Run `python scripts/check-module-manifest.py modules/<module>/module.toml`
   and the focused framework tests.

The default template is a headless manual worker job. It needs no Flask
Blueprint, frontend, Redis setup, database setup, or OAuth glue. The handler
receives `ctx` and `payload`; call `ctx.site()` when a logged-in Pywikibot site
is needed. Uncomment `blueprint_entry_point` and add frontend metadata only
when the module needs a custom web surface.

## External Module Workflow

For a separately versioned module:

1. Create the module repo as a Python package.
2. Expose an entry point in the `chuck_buckbot.modules` group.
3. Install it editable into the framework virtualenv while developing:

   ```bash
   python -m pip install -e ../module4awardhelper
   ```

4. Vendor a known-good snapshot into `vendor/modules/<module>/` before deploying
   the framework.

## Files In This Template

- `__init__.py` — Package marker.
- `module.toml` — Module manifest.
- `jobs.py` — Minimal framework-managed Pywikibot handler.
- `blueprint.py` — Flask Blueprint for module routes.
- `README.md` — This file.

See [MODULE_DEVELOPMENT_GUIDE.md](../../Deployment-docs/MODULE_DEVELOPMENT_GUIDE.md)
for the full module contract.
