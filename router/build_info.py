"""Local deployment/version metadata for templates and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
import re
import subprocess
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parent.parent
SEMVER_RE = re.compile(r"\d+\.\d+\.\d+")


@dataclass(frozen=True)
class ComponentBuildInfo:
    """Version and source revision displayed for one deployable component."""

    name: str
    version: str | None = None
    commit: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        """Return a JSON/template-safe component representation."""
        return {
            "name": self.name,
            "version": self.version,
            "commit": self.commit,
        }


@dataclass(frozen=True)
class DeploymentBuildInfo:
    """Framework build identity plus independently versioned vendored modules."""

    framework: ComponentBuildInfo
    modules: tuple[ComponentBuildInfo, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """Return a JSON/template-safe deployment representation."""
        return {
            "framework": self.framework.as_dict(),
            "modules": [module.as_dict() for module in self.modules],
        }


def _read_text(path: Path) -> str:
    """Read optional UTF-8 metadata, returning empty text when unavailable."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_framework_version() -> str | None:
    """Return the checked-in semantic framework version when valid."""
    text = _read_text(ROOT / "VERSION").strip()
    return text if SEMVER_RE.fullmatch(text) else None


def _git_short_commit() -> str | None:
    """Resolve the deployment commit from CI metadata or a bounded Git query."""
    # Deployment images may not contain .git; prefer build-system environment
    # values and use the subprocess only for source checkouts/local development.
    for env_name in (
        "GIT_COMMIT",
        "GITHUB_SHA",
        "SOURCE_COMMIT",
        "TOOLFORGE_BUILD_COMMIT",
    ):
        value = os.getenv(env_name, "").strip()
        if value:
            return value[:12]

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = result.stdout.strip()
    return commit or None


def _subtree_value(text: str, label: str) -> str | None:
    """Extract a backticked metadata value from the stable SUBTREE format."""
    match = re.search(rf"(?m)^- {re.escape(label)}:\s*`([^`]+)`\s*$", text)
    return match.group(1).strip() if match else None


def _pyproject_version(module_root: Path) -> str | None:
    """Read a vendored module's semantic version without importing it."""
    text = _read_text(module_root / "pyproject.toml")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
    if match and SEMVER_RE.fullmatch(match.group(1)):
        return match.group(1)
    return None


def _module_manifest_name(module_root: Path) -> str | None:
    """Read the first valid packaged module name beneath a vendored repository."""
    for manifest in sorted((module_root / "modules").glob("*/module.toml")):
        try:
            payload = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        name = payload.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _module_build_info(module_root: Path) -> ComponentBuildInfo | None:
    """Combine a vendored module's package version and subtree source commit."""
    subtree = _read_text(module_root / "SUBTREE.md")
    version = _pyproject_version(module_root)
    if not subtree and version is None:
        return None

    name = _module_manifest_name(module_root) or _subtree_value(subtree, "Framework module name") or module_root.name
    commit = _subtree_value(subtree, "Snapshot commit")
    return ComponentBuildInfo(name=name, version=version, commit=commit)


def _vendored_modules() -> tuple[ComponentBuildInfo, ...]:
    """Discover deterministic build metadata for checked-in module snapshots."""
    vendor_root = ROOT / "vendor" / "modules"
    if not vendor_root.exists():
        return ()

    modules = []
    for module_root in sorted(path for path in vendor_root.iterdir() if path.is_dir()):
        info = _module_build_info(module_root)
        if info is not None:
            modules.append(info)
    return tuple(modules)


@lru_cache(maxsize=1)
def deployment_build_info() -> DeploymentBuildInfo:
    """Return immutable build metadata, computing filesystem/Git probes once."""
    return DeploymentBuildInfo(
        framework=ComponentBuildInfo(
            name="framework",
            version=_read_framework_version(),
            commit=_git_short_commit(),
        ),
        modules=_vendored_modules(),
    )
