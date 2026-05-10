#!/usr/bin/env python3
"""Bump the framework patch version across version-bearing files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _read_version(path: Path) -> tuple[int, int, int]:
    text = path.read_text(encoding="utf-8").strip()
    match = SEMVER_RE.fullmatch(text)
    if not match:
        raise SystemExit(f"{path} does not contain a plain SemVer version")
    return tuple(int(part) for part in match.groups())


def _bump(version: tuple[int, int, int], part: str) -> str:
    major, minor, patch = version
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"Unsupported bump part: {part}")


def _update_json_version(path: Path, version: str, *, package_lock: bool = False) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = version
    if package_lock and isinstance(payload.get("packages"), dict):
        root_package = payload["packages"].get("")
        if isinstance(root_package, dict):
            root_package["version"] = version
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--part",
        choices=("major", "minor", "patch"),
        default="patch",
        help="SemVer component to bump.",
    )
    parser.add_argument(
        "--env-file",
        default="version.env",
        help="Path to write VERSION=<new version> for GitHub Actions.",
    )
    args = parser.parse_args()

    root = Path.cwd()
    version = _bump(_read_version(root / "VERSION"), args.part)

    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    _update_json_version(root / "package.json", version)
    _update_json_version(root / "package-lock.json", version, package_lock=True)
    Path(args.env_file).write_text(f"VERSION={version}\n", encoding="utf-8")

    print(version)


if __name__ == "__main__":
    main()
