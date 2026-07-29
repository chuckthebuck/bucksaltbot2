"""Salt Shack: contract-driven, forkable Pywikibot Saltlicks."""

from importlib import import_module
from typing import Any

__all__ = [
    "WorkflowSpec",
    "discover_saltlicks",
    "execute_workflow",
    "get_saltlick",
    "run_saltlick",
]

_LAZY_EXPORTS = {
    "WorkflowSpec": (".spec", "WorkflowSpec"),
    "discover_saltlicks": (".registry", "discover_saltlicks"),
    "execute_workflow": (".service", "execute_workflow"),
    "get_saltlick": (".registry", "get_saltlick"),
    "run_saltlick": (".service", "run_saltlick"),
}


def __getattr__(name: str) -> Any:
    """Load public helpers lazily so manifest discovery stays dependency-light."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
