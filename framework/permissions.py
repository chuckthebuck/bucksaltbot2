from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BotPermissions:
    domain_rights: set[str]
    domain_groups: dict[str, set[str]]


_registered_permissions: BotPermissions | None = None


def register_permissions(permissions: BotPermissions) -> None:
    global _registered_permissions
    _registered_permissions = permissions


def get_registered_permissions() -> BotPermissions:
    if _registered_permissions is None:
        raise RuntimeError("No BotPermissions has been registered")
    return _registered_permissions
