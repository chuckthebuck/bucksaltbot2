"""Bundled and vendored modules namespace for the framework."""

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)

_VENDOR_MODULES_ROOT = Path(__file__).resolve().parents[1] / "vendor" / "modules"
if _VENDOR_MODULES_ROOT.is_dir():
    for _module_dir in _VENDOR_MODULES_ROOT.iterdir():
        _candidate = _module_dir / "modules"
        if _candidate.is_dir():
            _candidate_str = str(_candidate)
            if _candidate_str not in __path__:
                __path__.append(_candidate_str)
