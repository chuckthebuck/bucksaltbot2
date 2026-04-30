# Template Module - Copy this to create your module

This is a starter template for developing a new Buckbot module.

## Quick Start

1. **Copy this directory** to `modules/your_module_name/`
2. **Update `module.toml`** with your module metadata
3. **Edit `blueprint.py`** to implement your module routes
4. **Test locally** with `ENABLE_MODULE_LOADING=1 pytest`
5. **Commit and deploy**

## Files in This Template

- `__init__.py` — Package marker (required, can be empty)
- `module.toml` — Module manifest with metadata and cron job definitions
- `blueprint.py` — Flask Blueprint with your module routes
- `README.md` — This file

## Next Steps

See the [Module Development Guide](../MODULE_DEVELOPMENT_GUIDE.md) for detailed documentation.
