"""Load Salt Shack's packaged framework manifest without path assumptions."""

from importlib.resources import files
import tomllib


def module_manifest():
    """Parse packaged TOML through import resources for wheel/editable installs."""
    text = files(__package__).joinpath("module.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)
