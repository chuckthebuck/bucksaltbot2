# Framework-Bundled Module Template

This template is for modules that intentionally live inside the framework repo,
such as rollback. Most new production modules should instead be separate Python
packages with a `chuck_buckbot.modules` entry point, installed editable during
development and vendored under `vendor/modules/<module>/` for deploy.

## Use This Template For Built-In Modules

1. Copy this directory to `modules/<module_name>/`.
2. Update `module.toml` with module metadata, cron jobs, frontend assets, docs,
   and module-owned rights.
3. Implement the module Blueprint and handlers.
4. Add the module name to `enabled-modules.txt`.
5. Run focused framework tests.

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
- `blueprint.py` — Flask Blueprint for module routes.
- `README.md` — This file.

See [MODULE_DEVELOPMENT_GUIDE.md](../../Deployment-docs/MODULE_DEVELOPMENT_GUIDE.md)
for the full module contract.
