"""Versioning convention checks."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def test_framework_version_files_match():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))

    assert SEMVER_RE.fullmatch(version)
    assert package["version"] == version
    assert lock["version"] == version
    assert lock["packages"][""]["version"] == version


def test_framework_release_workflow_tags_framework_versions():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert "git rev-list --count" in workflow
    assert "python3 scripts/bump-framework-version.py" in workflow
    assert "framework-v${VERSION}" in workflow
    assert "chore(release): framework-v${VERSION}" in workflow


def test_vendored_module_versions_match_package_metadata():
    module_roots = [
        path
        for path in (ROOT / "vendor/modules").iterdir()
        if (path / "pyproject.toml").exists()
    ]
    assert module_roots

    for module_root in module_roots:
        package_path = module_root / "package.json"
        if not package_path.exists():
            continue

        pyproject = (module_root / "pyproject.toml").read_text(encoding="utf-8")
        package = json.loads(package_path.read_text(encoding="utf-8"))

        match = re.search(r'(?m)^version\s*=\s*"(\d+\.\d+\.\d+)"\s*$', pyproject)
        assert match is not None, module_root
        version = match.group(1)

        assert package["version"] == version


def test_four_award_subtree_records_snapshot_commit():
    module_root = ROOT / "vendor/modules/four_award"
    pyproject = (module_root / "pyproject.toml").read_text(encoding="utf-8")
    subtree = (module_root / "SUBTREE.md").read_text(encoding="utf-8")

    match = re.search(r'(?m)^version\s*=\s*"(\d+\.\d+\.\d+)"\s*$', pyproject)
    assert match is not None
    assert "Snapshot commit:" in subtree


def test_four_award_release_workflow_tags_module_versions():
    workflow = (
        ROOT / "vendor/modules/four_award/.github/workflows/release.yml"
    ).read_text(encoding="utf-8")

    assert 'git tag "v${VERSION}"' in workflow
    assert 'gh release create "v${VERSION}"' in workflow
    assert "chore(release): v${VERSION}" in workflow
