"""Configuration parsing with deliberately conservative defaults."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def _bool(value: Any, default: bool) -> bool:
    """Parse a configuration boolean without treating arbitrary text as true."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    """Parse and clamp one integer configuration value."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


@dataclass(frozen=True)
class Settings:
    """Effective settings for one isolated run."""

    category_title: str = "Category:Other speedy deletions"
    dry_run: bool = True
    enabled: bool = True
    max_age_seconds: int = 7 * 24 * 60 * 60
    max_candidates: int = 250
    workers: int = 4
    deletion_reason: str = (
        "G7: uploader-requested deletion of recently created unused content"
    )

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None) -> Settings:
        """Build bounded settings from framework runtime configuration."""
        values = values or {}
        category = str(
            values.get("category_title", cls.category_title) or cls.category_title
        ).strip()
        if not category.casefold().startswith("category:"):
            category = f"Category:{category}"
        return cls(
            category_title=category,
            dry_run=_bool(values.get("dry_run"), True),
            enabled=_bool(values.get("enabled"), True),
            # G7 is fixed at strictly less than seven days. Administrators can
            # lower the window but cannot configure the bot beyond policy.
            max_age_seconds=_int(
                values.get("max_age_seconds"),
                cls.max_age_seconds,
                minimum=60,
                maximum=cls.max_age_seconds,
            ),
            max_candidates=_int(
                values.get("max_candidates"), 250, minimum=1, maximum=1000
            ),
            workers=_int(values.get("workers"), 4, minimum=1, maximum=16),
            deletion_reason=str(
                values.get("deletion_reason", cls.deletion_reason)
                or cls.deletion_reason
            ).strip(),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return settings without framework objects or credentials."""
        return {
            "category_title": self.category_title,
            "dry_run": self.dry_run,
            "enabled": self.enabled,
            "max_age_seconds": self.max_age_seconds,
            "max_candidates": self.max_candidates,
            "workers": self.workers,
            "deletion_reason": self.deletion_reason,
        }
