"""Validate metadata required by the standalone GitHub repository."""

from __future__ import annotations

import json
from pathlib import Path
import tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_URL = "https://github.com/chuckthebuck/chuck-the-salt-shack"


def test_python_and_node_metadata_point_to_canonical_repository():
    """Keep package links aligned with the public GitHub repository."""
    pyproject = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    package = json.loads(
        (REPOSITORY_ROOT / "package.json").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["urls"] == {
        "Homepage": REPOSITORY_URL,
        "Repository": REPOSITORY_URL,
        "Issues": f"{REPOSITORY_URL}/issues",
    }
    assert package["homepage"] == REPOSITORY_URL
    assert package["repository"]["url"] == f"git+{REPOSITORY_URL}.git"
    assert package["bugs"]["url"] == f"{REPOSITORY_URL}/issues"


def test_standalone_repository_has_automation_and_no_duplicate_docs():
    """Require GitHub automation and exclude retired duplicate documentation."""
    assert (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").is_file()
    assert (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").is_file()
    assert not (REPOSITORY_ROOT / "README 2.md").exists()
    assert not (
        REPOSITORY_ROOT
        / "modules"
        / "chuck_salt_shack"
        / "docs"
        / "saltlick 2.md"
    ).exists()
