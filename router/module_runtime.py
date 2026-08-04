"""Integrate enabled module web surfaces with the Flask application.

The registry validates and persists metadata without activating module runtime
code.  This module is the web-side activation boundary: it imports an enabled
module, resolves its optional Flask blueprint, and registers that blueprint on
the host application.  Import and factory failures are contained per module so
one broken extension does not prevent unrelated blueprints from loading.

This is failure isolation, not a security sandbox.  A registered blueprint runs
inside the Flask process and must be trusted application code.  Scheduled and
manual job handlers follow a different path through ``module_runner``; manual
runs are placed in a child process by ``module_job_controller`` so timeout and
cancellation can terminate the handler without killing the web process.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import import_module
import logging
from types import ModuleType
from typing import Any

from flask import Flask

from app import is_maintainer
from logger import Logger
from router.module_registry import (
    ModuleDefinition,
    ModuleRecord,
    get_module_definition,
    user_has_module_access,
)

LOGGER = logging.getLogger(__name__)


class _FallbackLogger:
    """Minimal logger used when the file-backed framework logger is unavailable."""

    def __init__(self, name: str):
        """Retain a component name for readable development output."""
        self.name = name

    def log(self, message: str) -> None:
        """Emit one namespaced message through the universally available stdout."""
        print(f"[{self.name}] {message}")


def _build_logger(name: str):
    """Build the normal module logger, falling back safely in dev/test contexts.

    Local import/manifest tooling often lacks the Toolforge data directory that
    :class:`logger.Logger` expects.  Logging must not make module discovery fail,
    so construction errors degrade to a stdout-compatible ``log`` interface.
    """
    if not os.environ.get("TOOL_DATA_DIR") and not os.environ.get("NOTDEV"):
        return _FallbackLogger(name)

    try:
        return Logger(name)
    except Exception:
        return _FallbackLogger(name)


@dataclass(frozen=True)
class ModuleContext:
    """Web-side module metadata, access decision, and scoped service handles.

    ``env`` is an explicit copy supplied by the caller rather than a reference
    to ``os.environ``.  This avoids accidentally handing a module the host's
    entire credential environment through the context object.  It is not the
    job handler context from ``module_runner.ModuleRunContext``.
    """

    module_name: str
    definition: ModuleDefinition
    username: str | None
    has_access: bool
    redis_namespace: str
    logger: Logger
    env: dict[str, str]
    module: ModuleType | None = None


@dataclass(frozen=True)
class LoadedModule:
    """Pair a registry record with the import and blueprint it produced."""

    record: ModuleRecord
    module_object: ModuleType | None = None
    blueprint: Any = None

    @property
    def definition(self) -> ModuleDefinition:
        """Expose the record's immutable definition to registration callers."""
        return self.record.definition


def build_module_context(
    module_name: str,
    *,
    username: str | None = None,
    env: dict[str, str] | None = None,
) -> ModuleContext | None:
    """Build a context for a stored module and resolve the caller's access.

    Registry presence, not module enablement, controls whether a context can be
    built.  Anonymous callers receive ``has_access=False`` without consulting
    policy.  The caller-provided environment mapping is copied to keep later
    mutation on either side from leaking across the boundary.
    """
    record = get_module_definition(module_name)
    if record is None:
        return None

    # Short-circuit anonymous callers before maintainer/authz/database lookups.
    has_access = bool(username and username.lower()) and user_has_module_access(
        record.definition.name,
        username,
        is_maintainer=is_maintainer(username),
    )

    return ModuleContext(
        module_name=record.definition.name,
        definition=record.definition,
        username=username,
        has_access=has_access,
        redis_namespace=record.definition.redis_namespace or module_name,
        logger=_build_logger(f"module.{record.definition.name}"),
        env=dict(env or {}),
    )


def _import_entry_point(entry_point: str) -> ModuleType:
    """Import the module portion of a validated ``module[:attribute]`` path.

    The attribute identifies a handler or other package API; legacy blueprint
    discovery only needs the owning module object and therefore ignores it.
    """
    module_name = entry_point.split(":", 1)[0].strip()
    if not module_name:
        raise ValueError("entry point must include a module import path")
    return import_module(module_name)


def _resolve_blueprint(entry_point: str):
    """Resolve an explicit blueprint path or the conventional module exports.

    With ``:attribute.path``, nested attributes are followed and a callable
    final value is treated as a zero-argument factory.  Without an attribute,
    ``blueprint`` is preferred and ``get_blueprint()`` is the compatibility
    fallback.  The imported module is returned for diagnostics/introspection.
    """
    module_name, separator, attribute_path = entry_point.partition(":")
    module_object = import_module(module_name)
    if not separator:
        blueprint = getattr(module_object, "blueprint", None)
        if blueprint is not None:
            return module_object, blueprint
        factory = getattr(module_object, "get_blueprint", None)
        return module_object, factory() if callable(factory) else None

    value: Any = module_object
    # Attribute traversal permits manifests to point at a blueprint nested in
    # an exported namespace without executing arbitrary expression syntax.
    for attribute in attribute_path.split("."):
        value = getattr(value, attribute)
    if callable(value):
        value = value()
    return module_object, value


def load_module(record: ModuleRecord) -> LoadedModule:
    """Import one module and resolve its optional blueprint without raising.

    An explicit ``blueprint_entry_point`` is authoritative.  Older manifests
    may omit it, in which case the general entry-point module is inspected for
    ``blueprint`` or ``get_blueprint``.  Import/factory failures are logged and
    represented by an empty :class:`LoadedModule` so startup can continue.
    """
    module_object = None
    blueprint = None

    if record.definition.blueprint_entry_point:
        # Do not fall back to the general entry point when an explicit web
        # boundary is broken; that could silently register a different surface.
        try:
            module_object, blueprint = _resolve_blueprint(
                record.definition.blueprint_entry_point
            )
        except Exception:
            LOGGER.exception(
                "Failed to load module blueprint %s",
                record.definition.blueprint_entry_point,
            )
        return LoadedModule(
            record=record,
            module_object=module_object,
            blueprint=blueprint,
        )

    try:
        module_object = _import_entry_point(record.definition.entry_point)
    except Exception:
        LOGGER.exception(
            "Failed to import module entry point %s",
            record.definition.entry_point,
        )

    if module_object is not None:
        # Conventional exports keep first-generation module packages working
        # even when their manifests predate ``blueprint_entry_point``.
        blueprint = getattr(module_object, "blueprint", None)
        if blueprint is None:
            factory = getattr(module_object, "get_blueprint", None)
            if callable(factory):
                try:
                    blueprint = factory()
                except Exception:
                    LOGGER.exception(
                        "Failed to create blueprint for module %s",
                        record.definition.name,
                    )

    return LoadedModule(record=record, module_object=module_object, blueprint=blueprint)


def load_enabled_modules() -> list[LoadedModule]:
    """Activate every registry-enabled module, preserving registry order."""
    # Resolve the listing function at call time so registry bootstrap and test
    # compatibility patches are complete before module imports begin.
    from router.module_registry import list_module_definitions

    return [load_module(record) for record in list_module_definitions(enabled_only=True)]


def register_enabled_modules(app: Flask) -> list[str]:
    """Register available enabled-module blueprints and return their names.

    A blueprint-owned prefix wins; otherwise the module receives ``/<name>``.
    Modules without a web surface remain valid cron/worker modules.  Flask
    ``ValueError`` failures (notably duplicate or invalid registration) are
    isolated to that module, while unexpected application errors still surface.
    """
    registered: list[str] = []
    for loaded in load_enabled_modules():
        blueprint = loaded.blueprint
        if blueprint is None:
            continue

        # API-oriented modules can own a versioned prefix.  The deterministic
        # name-based fallback prevents an unprefixed blueprint taking over root.
        url_prefix = (
            str(getattr(blueprint, "url_prefix", "") or "").strip()
            or f"/{loaded.definition.name}"
        )
        try:
            app.register_blueprint(blueprint, url_prefix=url_prefix)
        except ValueError:
            # Duplicate/invalid blueprint state should not hide independent
            # module surfaces during framework startup.
            LOGGER.exception(
                "Failed to register blueprint for module %s",
                loaded.definition.name,
            )
            continue
        registered.append(loaded.definition.name)

    return registered
