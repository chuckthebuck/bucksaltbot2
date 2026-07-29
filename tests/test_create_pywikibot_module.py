from pathlib import Path

import pytest


def test_scaffold_module_creates_minimal_manual_worker(tmp_path: Path):
    from scripts.create_pywikibot_module import scaffold_module
    from router.module_registry import load_module_definition

    module_dir = scaffold_module(
        tmp_path,
        "example_bot",
        title="Example Bot",
        enable=True,
    )

    definition = load_module_definition(module_dir / "module.toml")
    assert definition.name == "example_bot"
    assert definition.title == "Example Bot"
    assert definition.cron_jobs == ()
    assert definition.worker_jobs[0].handler == "modules.example_bot.jobs:run"
    assert (module_dir / "jobs.py").is_file()
    assert (tmp_path / "enabled-modules.txt").read_text(encoding="utf-8") == (
        "example_bot\n"
    )


def test_scaffold_module_can_create_scheduled_handler(tmp_path: Path):
    from scripts.create_pywikibot_module import scaffold_module
    from router.module_registry import load_module_definition

    module_dir = scaffold_module(
        tmp_path,
        "scheduled_bot",
        schedule="every hour",
    )

    definition = load_module_definition(module_dir / "module.toml")
    assert definition.worker_jobs == ()
    assert definition.cron_jobs[0].schedule == "0 * * * *"
    assert definition.cron_jobs[0].execution_mode == "handler"


def test_scaffold_module_refuses_to_overwrite_existing_module(tmp_path: Path):
    from scripts.create_pywikibot_module import scaffold_module

    scaffold_module(tmp_path, "example_bot")

    with pytest.raises(FileExistsError, match="already exists"):
        scaffold_module(tmp_path, "example_bot")
