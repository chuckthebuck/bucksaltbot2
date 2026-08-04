"""Immutable value objects shared by parsing, planning, and persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FileChangeTarget:
    """One normalized Commons file-page target with optional row metadata."""
    title: str
    user: str | None = None
    summary_hint: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        """Return a JSON-ready representation for APIs and durable chunks."""
        return asdict(self)


@dataclass(frozen=True)
class FileChangeOperation:
    """One validated replace, prepend, or append operation."""
    mode: str
    find: str = ""
    replace: str = ""
    prepend: str = ""
    append: str = ""
    edit_summary: str = ""
    use_regex: bool = False

    def as_dict(self) -> dict[str, str]:
        """Return the canonical operation recorded with a run result."""
        return asdict(self)


@dataclass(frozen=True)
class FileChangePlanItem:
    """Preview/apply outcome for one target, including its reviewable diff."""
    title: str
    status: str
    old_text: str = ""
    new_text: str = ""
    diff: str = ""
    error: str | None = None

    @property
    def changed(self) -> bool:
        """Return whether planning produced text different from the source."""
        return self.status == "changed"

    def as_dict(self) -> dict[str, str | bool | None]:
        """Serialize stored fields plus the derived ``changed`` flag."""
        payload = asdict(self)
        payload["changed"] = self.changed
        return payload
