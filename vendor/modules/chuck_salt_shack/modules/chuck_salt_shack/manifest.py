"""Packaged Chuck the Salt Shack module-manifest loader."""

from importlib.resources import files
import tomllib


def module_manifest():
    """Load the packaged TOML manifest as the single source of truth."""
    text = files(__package__).joinpath("module.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)
