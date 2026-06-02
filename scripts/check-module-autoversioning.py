#!/usr/bin/env python3
"""Check vendored module repos have release autoversioning metadata."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


VERSION_RE = re.compile(r'(?m)^version\s*=\s*"(\d+\.\d+\.\d+)"\s*$')
STALE_UA_RE = re.compile(
    r"(Buckbot|FourAwardHelper|ChuckFileChanger)(?:-local)?/\d+\.\d+(?:\.\d+)?"
)


def pyproject_version(path: Path) -> str:
    match = VERSION_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"{path} does not contain a SemVer project version")
    return match.group(1)


def package_version(path: Path) -> str | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"{path} does not contain a SemVer version")
    return version


def check_module(module_dir: Path) -> list[str]:
    errors: list[str] = []
    workflow = module_dir / ".github" / "workflows" / "release.yml"
    pyproject = module_dir / "pyproject.toml"
    package = module_dir / "package.json"

    if not pyproject.exists():
        return errors
    if not workflow.exists():
        errors.append(f"{module_dir}: missing .github/workflows/release.yml")

    try:
        py_version = pyproject_version(pyproject)
        pkg_version = package_version(package)
        if pkg_version is not None and pkg_version != py_version:
            errors.append(
                f"{module_dir}: package.json version {pkg_version} != pyproject.toml version {py_version}"
            )
    except ValueError as exc:
        errors.append(str(exc))

    if workflow.exists():
        text = workflow.read_text(encoding="utf-8")
        required = ("chore(release):", "git tag", "gh release create")
        missing = [needle for needle in required if needle not in text]
        if missing:
            errors.append(
                f"{module_dir}: release workflow missing markers: {', '.join(missing)}"
            )

    return errors


def check_user_agent_versions(root: Path) -> list[str]:
    errors: list[str] = []
    paths = [
        root / ".env.example",
        root / "http_config.py",
        root / "Deployment-docs",
        root / "vendor" / "modules",
    ]
    for base in paths:
        if not base.exists():
            continue
        files = [base] if base.is_file() else base.rglob("*")
        for path in files:
            if not path.is_file() or path.suffix not in {".py", ".md", ".toml", ".example"}:
                continue
            if ".git" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if STALE_UA_RE.search(text):
                errors.append(f"{path}: hardcoded User-Agent version must derive from release")
    return errors


def main() -> int:
    root = Path.cwd()
    module_root = root / "vendor" / "modules"
    errors: list[str] = []
    for module_dir in sorted(module_root.iterdir() if module_root.exists() else []):
        if module_dir.is_dir():
            errors.extend(check_module(module_dir))
    errors.extend(check_user_agent_versions(root))

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("module autoversioning ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
