from pathlib import Path

from self_delete.manifest import module_manifest


def test_manifest_declares_isolated_forbid_concurrency_cron_job():
    manifest = module_manifest()
    job = manifest["jobs"][0]

    assert manifest["name"] == "self_delete"
    assert manifest["ui"] is True
    assert manifest["frontend"]["bundled"] is True
    assert manifest["frontend"]["mount_id"] == "self-delete-app"
    assert job["handler"] == "self_delete.service:run_self_delete"
    assert job["execution_mode"] == "k8s_job"
    assert job["concurrency_policy"] == "forbid"
    assert job["run"] == "every 15 minutes"


def test_package_contains_manifest_and_documentation():
    package_root = Path(__file__).resolve().parents[1] / "modules" / "self_delete"
    assert (package_root / "module.toml").is_file()
    assert (package_root / "docs" / "self_delete.md").is_file()
    assert (package_root / "frontend" / "entry.ts").is_file()


def test_framework_loader_accepts_packaged_manifest():
    """The installed entry point exposes a complete UI-enabled manifest."""
    manifest = module_manifest()

    assert manifest["name"] == "self_delete"
    assert manifest["ui"] is True
    assert manifest["frontend"]["bundled"] is True
    assert manifest["frontend"]["mount_id"] == "self-delete-app"
