"""Manifest entry point for Chuck the File Changer."""

from importlib.resources import files
import tomllib


def module_manifest():
    """Load the packaged TOML manifest as the single source of truth."""
    manifest_text = files(__package__).joinpath("module.toml").read_text(
        encoding="utf-8"
    )
    return tomllib.loads(manifest_text)
