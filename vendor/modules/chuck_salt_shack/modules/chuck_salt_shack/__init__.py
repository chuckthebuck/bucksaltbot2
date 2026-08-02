"""Salt Shack: contract-driven, forkable Pywikibot Saltlicks."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

_LAZY_EXPORTS = {
    "WorkflowSpec": (".spec", "WorkflowSpec"),
    "discover_saltlicks": (".registry", "discover_saltlicks"),
    "execute_workflow": (".service", "execute_workflow"),
    "get_saltlick": (".registry", "get_saltlick"),
    "run_saltlick": (".service", "run_saltlick"),
}

__all__ = tuple(_LAZY_EXPORTS)

if TYPE_CHECKING:
    from .registry import discover_saltlicks, get_saltlick
    from .service import execute_workflow, run_saltlick
    from .spec import WorkflowSpec


def __getattr__(name: str) -> Any:
    """Load public helpers lazily so manifest discovery stays dependency-light."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
