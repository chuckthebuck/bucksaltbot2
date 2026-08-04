"""Public, dependency-light access to Salt Shack's execution helpers.

Imports are lazy so the framework can inspect package and manifest metadata
without eagerly importing PyYAML, Pywikibot-facing adapters, or worker code.
"""

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "WorkflowSpec": (".spec", "WorkflowSpec"),
    "discover_saltlicks": (".registry", "discover_saltlicks"),
    "execute_workflow": (".service", "execute_workflow"),
    "get_saltlick": (".registry", "get_saltlick"),
    "run_saltlick": (".service", "run_saltlick"),
}

__all__ = tuple(_LAZY_EXPORTS)

def __getattr__(name: str) -> Any:
    """Resolve a declared public helper once and cache it in module globals."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    # Match ordinary import semantics after first access and avoid repeating
    # import/lookup work for subsequent attribute reads.
    globals()[name] = value
    return value
