"""Immutable values passed between discovery, validation, and deletion."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Candidate:
    """One file discovered in the configured category."""

    title: str
    page_id: int | None = None


@dataclass(frozen=True)
class Inspection:
    """A complete policy decision from one fresh wiki snapshot."""

    candidate: Candidate
    eligible: bool
    reason_code: str
    reason_detail: str
    uploader: str | None = None
    requester: str | None = None
    upload_timestamp: datetime | None = None
    checks: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the JSON-safe audit representation."""
        return {
            "title": self.candidate.title,
            "page_id": self.candidate.page_id,
            "eligible": self.eligible,
            "reason_code": self.reason_code,
            "reason_detail": self.reason_detail,
            "uploader": self.uploader,
            "requester": self.requester,
            "upload_timestamp": (
                self.upload_timestamp.isoformat() if self.upload_timestamp else None
            ),
            "checks": self.checks,
        }
