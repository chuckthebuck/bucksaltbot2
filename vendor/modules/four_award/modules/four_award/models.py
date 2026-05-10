from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Literal


@dataclass
class FourAwardNomination:
    section_title: str
    section_index: int
    raw_text: str
    users: List[str]
    article: str
    dyknom: Optional[str] = None
    dyk: Optional[str] = None
    ga: Optional[str] = None
    fac: Optional[str] = None
    comments: Optional[str] = None


@dataclass
class FourAwardRecord:
    user: str
    article: str
    award_date: Optional[str]
    creation_date: Optional[str]
    dyk_date: Optional[str]
    ga_date: Optional[str]
    fa_date: Optional[str]
    display_user: Optional[str] = None


@dataclass
class PageCreation:
    user: Optional[str]
    date: Optional[date]


@dataclass
class VerificationIssue:
    code: str
    reason: str


@dataclass
class VerificationStage:
    key: str
    label: str
    status: str
    reason: str = ""
    expected_users: List[str] = field(default_factory=list)
    evidence_users: List[str] = field(default_factory=list)
    pages: List[str] = field(default_factory=list)
    start: Optional[str] = None
    end: Optional[str] = None
    details: dict[str, str] = field(default_factory=dict)


Status = Literal["approved", "failed_to_verify", "manual_review_needed"]


@dataclass
class NominationResult:
    nomination: FourAwardNomination
    status: Status
    issues: List[VerificationIssue] = field(default_factory=list)
    record: Optional[FourAwardRecord] = None
    stage_checks: List[VerificationStage] = field(default_factory=list)
