"""Runtime helpers for framework-loaded modules."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import import_module
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


class _FallbackLogger:
    def __init__(self, name: str):
        self.name = name

    def log(self, message: str) -> None:
        print(f"[{self.name}] {message}")


def _build_logger(name: str):
    if not os.environ.get("TOOL_DATA_DIR") and not os.environ.get("NOTDEV"):
        return _FallbackLogger(name)

    try:
        return Logger(name)
    except Exception:
        return _FallbackLogger(name)


@dataclass(frozen=True)
class ModuleContext:
    """Runtime context passed to module code."""

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
    """Imported runtime state for a module."""

    record: ModuleRecord
    module_object: ModuleType | None = None
    blueprint: Any = None

    @property
    def definition(self) -> ModuleDefinition:
        return self.record.definition


def build_module_context(
    module_name: str,
    *,
    username: str | None = None,
    env: dict[str, str] | None = None,
) -> ModuleContext | None:
    """Create a runtime context for a module if it exists."""
    record = get_module_definition(module_name)
    if record is None:
        return None

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
    module_name = entry_point.split(":", 1)[0].strip()
    if not module_name:
        raise ValueError("entry point must include a module import path")
    return import_module(module_name)


def load_module(record: ModuleRecord) -> LoadedModule:
    """Import the module entry point if it exists."""
    module_object = None
    blueprint = None

    try:
        module_object = _import_entry_point(record.definition.entry_point)
    except Exception:
        module_object = None

    if module_object is not None:
        blueprint = getattr(module_object, "blueprint", None)
        if blueprint is None:
            factory = getattr(module_object, "get_blueprint", None)
            if callable(factory):
                try:
                    blueprint = factory()
                except Exception:
                    blueprint = None

    return LoadedModule(record=record, module_object=module_object, blueprint=blueprint)


def load_enabled_modules() -> list[LoadedModule]:
    """Load every enabled module known to the registry."""
    from router.module_registry import list_module_definitions

    return [load_module(record) for record in list_module_definitions(enabled_only=True)]


def register_enabled_modules(app: Flask) -> list[str]:
    """Register any available module blueprints on the Flask app.

    Modules that do not expose a blueprint are left out for now; they can still
    use the shared cron and access APIs.
    """
    registered: list[str] = []
    for loaded in load_enabled_modules():
        blueprint = loaded.blueprint
        if blueprint is None:
            continue

        url_prefix = f"/{loaded.definition.name}"
        try:
            app.register_blueprint(blueprint, url_prefix=url_prefix)
        except ValueError:
            # Duplicate registration or invalid blueprint should not break the
            # whole framework startup; just skip and continue.
            continue
        registered.append(loaded.definition.name)

    return registered
