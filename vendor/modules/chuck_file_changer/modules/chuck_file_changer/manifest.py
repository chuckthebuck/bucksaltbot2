"""Manifest entry point for Chuck the File Changer."""

from importlib.resources import files
import tomllib


def module_manifest():
    """Parse packaged TOML in editable installs and built distributions."""
    manifest_text = files(__package__).joinpath("module.toml").read_text(
        encoding="utf-8"
    )
    return tomllib.loads(manifest_text)
