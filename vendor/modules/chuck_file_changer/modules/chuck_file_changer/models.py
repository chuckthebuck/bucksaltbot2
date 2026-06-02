from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FileChangeTarget:
    title: str
    user: str | None = None
    summary_hint: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class FileChangeOperation:
    mode: str
    find: str = ""
    replace: str = ""
    prepend: str = ""
    append: str = ""
    edit_summary: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class FileChangePlanItem:
    title: str
    status: str
    old_text: str = ""
    new_text: str = ""
    diff: str = ""
    error: str | None = None

    @property
    def changed(self) -> bool:
        return self.status == "changed"

    def as_dict(self) -> dict[str, str | bool | None]:
        payload = asdict(self)
        payload["changed"] = self.changed
        return payload
