from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BotAction(ABC):
    @abstractmethod
    def execute_item(
        self,
        item_key: str,
        item_target: str,
        summary: str | None,
        requested_by: str,
        site: Any,
        dry_run: bool,
    ) -> None:
        """Execute a single queued item."""


_registered_action: BotAction | None = None


def register_action(action: BotAction) -> None:
    global _registered_action
    _registered_action = action


def get_registered_action() -> BotAction:
    if _registered_action is None:
        raise RuntimeError("No BotAction has been registered")
    return _registered_action
