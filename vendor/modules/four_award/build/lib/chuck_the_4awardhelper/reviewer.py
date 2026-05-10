from __future__ import annotations

import re
from datetime import date
from typing import Optional

from .config import ALLOW_AUTOMATED_APPROVAL, IGNORE_EXISTING_RECORDS, RECORDS_PAGE
from .models import (
    FourAwardNomination,
    FourAwardRecord,
    NominationResult,
    VerificationIssue,
    VerificationStage,
)
from .util import award_date, clean_wiki_value, date_window, normalize_title, normalize_user, parse_date, to_iso
from .wiki import get_wiki


def _issue(code: str, reason: str) -> VerificationIssue:
    return VerificationIssue(code=code, reason=reason)


def _stage(
    key: str,
    label: str,
    status: str,
    reason: str = "",
    *,
    expected_users: list[str] | None = None,
    evidence_users: set[str] | list[str] | None = None,
    pages: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    details: dict[str, str] | None = None,
) -> VerificationStage:
    return VerificationStage(
        key=key,
        label=label,
        status=status,
        reason=reason,
        expected_users=list(expected_users or []),
        evidence_users=sorted(evidence_users or [], key=lambda value: value.casefold()),
        pages=list(pages or []),
        start=to_iso(start),
        end=to_iso(end),
        details=details or {},
    )


def _contains_record(records_text: str, article: str, users: list[str]) -> bool:
    haystack = records_text.replace("_", " ").casefold()
    if normalize_title(article).casefold() not in haystack:
        return False
    return any(normalize_user(user) in haystack for user in users)


def _action_date(text: str, action_name: str) -> Optional[date]:
    value = _action_value(text, action_name)
    return parse_date(value)


def _action_value(text: str, action_name: str) -> str:
    params = _template_params(text)
    for key, value in params.items():
        match = re.fullmatch(r"action(\d+)", key, re.I)
        if not match or action_name.casefold() not in value.casefold():
            continue
        return params.get(f"action{match.group(1)}date", "").strip()
    return (
        params.get(f"{action_name.casefold()}date")
        or params.get(f"{action_name.casefold()}_date")
        or ""
    ).strip()


def _action_link(text: str, action_name: str) -> str:
    params = _template_params(text)
    for key, value in params.items():
        match = re.fullmatch(r"action(\d+)", key, re.I)
        if not match or action_name.casefold() not in value.casefold():
            continue
        link_value = params.get(f"action{match.group(1)}link", "")
        if link_value:
            return _link_target(link_value)
    return ""


def _template_params(template_text: str) -> dict[str, str]:
    text = template_text.strip()
    if text.startswith("{{") and text.endswith("}}"):
        text = text[2:-2]
    pieces: list[str] = []
    current: list[str] = []
    depth = 0
    i = 0
    while i < len(text):
        pair = text[i : i + 2]
        if pair in {"{{", "[["}:
            depth += 1
            current.append(pair)
            i += 2
            continue
        if pair in {"}}", "]]"} and depth:
            depth -= 1
            current.append(pair)
            i += 2
            continue
        if text[i] == "|" and depth == 0:
            pieces.append("".join(current))
            current = []
            i += 1
            continue
        current.append(text[i])
        i += 1
    pieces.append("".join(current))

    params: dict[str, str] = {}
    for piece in pieces[1:]:
        if "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        params[key.strip().casefold()] = value.strip()
    return params


def _link_target(value: str) -> str:
    match = re.search(r"\[\[([^|\]]+)", value)
    if match:
        return normalize_title(match.group(1))
    return normalize_title(clean_wiki_value(value))


def _raw_link_target(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"\[\[([^|\]]+)", value)
    return normalize_title(match.group(1)) if match else normalize_title(clean_wiki_value(value))


def _looks_like_process_page(title: str, kind: str) -> bool:
    normalized = normalize_title(title).casefold()
    if kind == "ga":
        return normalized.startswith("talk:") or "/ga" in normalized
    if kind == "fa":
        return "featured article candidates/" in normalized or "/fac" in normalized
    return True


def _article_history_template(text: str) -> str:
    match = re.search(r"\{\{\s*Article history\b.*?\n\}\}", text, re.I | re.S)
    if match:
        return match.group(0)
    match = re.search(r"\{\{\s*Article history\b.*?\}\}", text, re.I | re.S)
    return match.group(0) if match else ""


def _has_fa_status(history: str) -> bool:
    if not history:
        return False
    if re.search(r"\|\s*(currentstatus|status)\s*=\s*FA\b", history, re.I):
        return True
    return bool(
        re.search(
            r"\|\s*action\d+\s*=\s*(?:FAC|FAR).*?\|\s*action\d+result\s*=\s*(?:promoted|kept)",
            history,
            re.I | re.S,
        )
    )


def _date_from_text(text: str) -> str:
    parsed = parse_date(text)
    if parsed:
        return to_iso(parsed)
    match = re.search(
        r"\b(\d{1,2}\s+[A-Z][a-z]+\s+\d{4}|[A-Z][a-z]+\s+\d{1,2},\s+\d{4}|\d{4}-\d{1,2}-\d{1,2})\b",
        text,
    )
    return to_iso(match.group(1)) if match else ""


def _bot_process_date(text: str, bot_names: tuple[str, ...]) -> str:
    bot_lines = [
        line
        for line in text.splitlines()
        if any(bot.casefold() in line.casefold() for bot in bot_names)
    ]
    for line in reversed(bot_lines):
        found = _date_from_text(line)
        if found:
            return found
    return ""


def _latest_process_date(article: str, pages: list[str], bot_names: tuple[str, ...]) -> str:
    wiki = get_wiki()
    for page in pages:
        if not page:
            continue
        title = _process_page_title(article, page)
        bot_date = _bot_process_date(_safe_text(title), bot_names)
        if bot_date:
            return bot_date
        try:
            revision_date = wiki.latest_revision_date(title)
        except Exception:
            revision_date = None
        if revision_date:
            return to_iso(revision_date)
    return ""


def _record_for(nomination: FourAwardNomination, history: str, creation_date: Optional[date]) -> FourAwardRecord:
    dyk_date = _action_value(history, "DYK") or nomination.dyk or ""
    ga_date = (
        _action_value(history, "GAN")
        or _action_value(history, "GA")
        or _latest_process_date(nomination.article, _ga_pages(nomination, history), ("ChristieBot",))
    )
    fa_date = (
        _action_value(history, "FAC")
        or _action_value(history, "FA")
        or _latest_process_date(nomination.article, _fa_pages(nomination, history), ("FACBot",))
    )
    return FourAwardRecord(
        user=nomination.users[0],
        article=nomination.article,
        award_date=award_date(),
        creation_date=to_iso(creation_date),
        dyk_date=dyk_date,
        ga_date=ga_date,
        fa_date=fa_date,
    )


def _has_milestone_evidence(nomination: FourAwardNomination, history: str, label: str) -> bool:
    if label == "DYK date":
        return bool(_action_value(history, "DYK") or nomination.dyk or nomination.dyknom)
    if label == "GA date":
        return any(_ga_pages(nomination, history))
    if label == "FA date":
        return any(_fa_pages(nomination, history))
    return False


def _missing_users(expected: list[str], evidence: set[str]) -> list[str]:
    normalized = {normalize_user(user) for user in evidence}
    return [user for user in expected if normalize_user(user) not in normalized]


def _signature_users(text: str) -> set[str]:
    users = set()
    for pattern in (
        r"\[\[\s*User:([^|\]/#]+)",
        r"\[\[\s*User talk:([^|\]/#]+)",
        r"\{\{\s*u(?:ser)?\s*\|\s*([^}|]+)",
    ):
        for match in re.finditer(pattern, text, re.I):
            users.add(clean_wiki_value(match.group(1)))
    return users


def _safe_text(title: str) -> str:
    try:
        return get_wiki().get_text(title)
    except Exception:
        return ""


def _process_page_users(title: str, start: date | None = None, end: date | None = None) -> set[str]:
    if not title:
        return set()
    wiki = get_wiki()
    users = wiki.revision_users(title, start=start, end=end)
    users.update(_signature_users(_safe_text(title)))
    return users


def _stage_evidence_users(article: str, process_pages: list[str], start: date | None, end: date | None) -> set[str]:
    wiki = get_wiki()
    users = wiki.revision_users(article, start=start, end=end)
    for page in process_pages:
        users.update(_process_page_users(page, start=start, end=end))
    return users


def _default_dyk_page(nomination: FourAwardNomination) -> str:
    return nomination.dyknom or f"Template:Did you know nominations/{nomination.article}"


def _process_page_title(article: str, page: str) -> str:
    normalized = normalize_title(page)
    if normalized.startswith("/"):
        return f"Talk:{article}{normalized}"
    return normalized


def _ga_pages(nomination: FourAwardNomination, history: str) -> list[str]:
    nominated = _raw_link_target(nomination.ga)
    return [
        nominated if _looks_like_process_page(nominated, "ga") else "",
        _action_link(history, "GAN"),
        _action_link(history, "GA"),
        f"Talk:{nomination.article}/GA1",
    ]


def _fa_pages(nomination: FourAwardNomination, history: str) -> list[str]:
    nominated = _raw_link_target(nomination.fac)
    return [
        nominated if _looks_like_process_page(nominated, "fa") else "",
        _action_link(history, "FAC"),
        _action_link(history, "FA"),
        f"Wikipedia:Featured article candidates/{nomination.article}/archive1",
    ]


def _contribution_review(
    nomination: FourAwardNomination,
    history: str,
    record: FourAwardRecord,
) -> tuple[list[VerificationIssue], list[VerificationStage]]:
    wiki = get_wiki()
    issues: list[VerificationIssue] = []
    stages: list[VerificationStage] = []
    creation = wiki.page_creation(nomination.article)
    creation_start, creation_end = date_window(creation.date, 0, 7)
    creation_users = set()
    if creation.user:
        creation_users.add(creation.user)
    creation_users.update(wiki.revision_users(nomination.article, start=creation_start, end=creation_end))

    missing = _missing_users(nomination.users, creation_users)
    if missing:
        reason = "Could not verify page creation or early article edits for " + ", ".join(missing) + "."
        issues.append(
            _issue(
                "missing_creation_contribution",
                reason,
            )
        )
    else:
        reason = "Verified page creator or early article edit by every credited user."
    stages.append(
        _stage(
            "creation_contribution",
            "Page creation / early edits",
            "failed" if missing else "passed",
            reason,
            expected_users=nomination.users,
            evidence_users=creation_users,
            pages=[nomination.article],
            start=creation_start,
            end=creation_end,
            details={
                "creation_date": to_iso(creation.date),
                "first_revision_user": creation.user or "",
            },
        )
    )

    dyk_start = parse_date(record.creation_date)
    dyk_end = parse_date(record.dyk_date)
    ga_start = dyk_end or dyk_start
    ga_end = parse_date(record.ga_date)
    fa_start = ga_end or ga_start
    fa_end = parse_date(record.fa_date)

    checks = (
        (
            "missing_dyk_contribution",
            "DYK",
            [_default_dyk_page(nomination), _action_link(history, "DYK")],
            dyk_start,
            dyk_end,
        ),
        (
            "missing_ga_contribution",
            "GA",
            _ga_pages(nomination, history),
            ga_start,
            ga_end,
        ),
        (
            "missing_fa_contribution",
            "FA",
            _fa_pages(nomination, history),
            fa_start,
            fa_end,
        ),
    )
    for code, label, pages, start, end in checks:
        clean_pages = [
            page
            for page in dict.fromkeys(
                _process_page_title(nomination.article, page)
                for page in pages
                if page
            )
            if page
        ]
        evidence_users = _stage_evidence_users(nomination.article, clean_pages, start, end)
        missing = _missing_users(nomination.users, evidence_users)
        if missing:
            reason = f"Could not verify {label} process-page participation or article edits for " + ", ".join(missing) + "."
            issues.append(
                _issue(
                    code,
                    reason,
                )
            )
        else:
            reason = f"Verified {label} participation or article edits by every credited user."
        stages.append(
            _stage(
                code.removeprefix("missing_"),
                f"{label} contribution",
                "failed" if missing else "passed",
                reason,
                expected_users=nomination.users,
                evidence_users=evidence_users,
                pages=[nomination.article] + clean_pages,
                start=start,
                end=end,
            )
        )
    return issues, stages


def review_nomination(nomination: FourAwardNomination) -> NominationResult:
    stages: list[VerificationStage] = []
    if not nomination.article:
        issue = _issue("missing_article", "The nomination does not identify an article.")
        stages.append(_stage("nomination_article", "Nomination article", "failed", issue.reason))
        return NominationResult(nomination, "failed_to_verify", [issue], stage_checks=stages)
    if not nomination.users:
        issue = _issue("missing_users", "No credited user was supplied; self-nominations need reviewer confirmation.")
        stages.append(_stage("credited_users", "Credited users", "failed", issue.reason))
        return NominationResult(nomination, "manual_review_needed", [issue], stage_checks=stages)

    wiki = get_wiki()
    if not wiki.exists(nomination.article):
        issue = _issue("missing_article_page", f"[[{nomination.article}]] does not exist.")
        stages.append(_stage("article_page", "Article page exists", "failed", issue.reason, pages=[nomination.article]))
        return NominationResult(nomination, "failed_to_verify", [issue], stage_checks=stages)
    stages.append(_stage("article_page", "Article page exists", "passed", "Article page exists.", pages=[nomination.article]))

    if IGNORE_EXISTING_RECORDS:
        stages.append(
            _stage(
                "duplicate_record",
                "Existing Four Award record",
                "skipped",
                "Existing records check skipped for historical dry-run testing.",
                pages=[RECORDS_PAGE],
            )
        )
    elif _contains_record(wiki.get_text(RECORDS_PAGE), nomination.article, nomination.users):
        issue = _issue("duplicate_record", "The article and user already appear in the Four Award records.")
        stages.append(_stage("duplicate_record", "Existing Four Award record", "failed", issue.reason, pages=[RECORDS_PAGE]))
        return NominationResult(nomination, "failed_to_verify", [issue], stage_checks=stages)
    else:
        stages.append(_stage("duplicate_record", "Existing Four Award record", "passed", "No matching existing record was found.", pages=[RECORDS_PAGE]))

    history = _article_history_template(wiki.get_text(f"Talk:{nomination.article}"))
    if not history:
        stages.append(
            _stage(
                "article_history",
                "Article history template",
                "skipped",
                "{{Article history}} was not found; using nomination links and page history evidence.",
                pages=[f"Talk:{nomination.article}"],
            )
        )
    else:
        stages.append(_stage("article_history", "Article history template", "passed", "{{Article history}} was found.", pages=[f"Talk:{nomination.article}"]))
    has_fac_nomination = any(page for page in _fa_pages(nomination, history))
    if history and not _has_fa_status(history) and not has_fac_nomination:
        issue = _issue("not_featured_article", "{{Article history}} does not show current FA status.")
        stages.append(_stage("fa_status", "Featured Article status", "failed", issue.reason, pages=[f"Talk:{nomination.article}"]))
        return NominationResult(nomination, "failed_to_verify", [issue], stage_checks=stages)
    if history and _has_fa_status(history):
        fa_status_reason = "{{Article history}} shows FA status."
    else:
        fa_status_reason = "FAC link is present in the nomination; FA status should be checked against FAC evidence."
    stages.append(
        _stage(
            "fa_status",
            "Featured Article status",
            "passed",
            fa_status_reason,
            pages=[f"Talk:{nomination.article}"] + [page for page in _fa_pages(nomination, history) if page],
        )
    )

    creation = wiki.page_creation(nomination.article)
    record = _record_for(nomination, history, creation.date)
    issues: list[VerificationIssue] = []
    for value, label in (
        (record.creation_date, "creation date"),
        (record.dyk_date, "DYK date"),
        (record.ga_date, "GA date"),
        (record.fa_date, "FA date"),
    ):
        if not value and not _has_milestone_evidence(nomination, history, label):
            issues.append(_issue("missing_milestone", f"Could not determine the {label}."))
    stages.append(
        _stage(
            "milestone_dates",
            "Milestone dates",
            "failed" if issues else "passed",
            "Could not determine all required milestone dates." if issues else "Creation, DYK, GA, and FA dates were found.",
            details={
                "creation_date": record.creation_date or "",
                "dyk_date": record.dyk_date or "",
                "ga_date": record.ga_date or "",
                "fa_date": record.fa_date or "",
            },
        )
    )
    if not issues:
        contribution_issues, contribution_stages = _contribution_review(nomination, history, record)
        issues.extend(contribution_issues)
        stages.extend(contribution_stages)

    if issues or not ALLOW_AUTOMATED_APPROVAL:
        if not ALLOW_AUTOMATED_APPROVAL:
            issue = _issue(
                "automated_approval_disabled",
                "Automated approval is disabled by configuration; dry-run can verify evidence but will not approve.",
            )
            issues.append(issue)
            stages.append(
                _stage(
                    "automated_approval",
                    "Automated approval gate",
                    "blocked",
                    issue.reason,
                    details={"allow_automated_approval": str(ALLOW_AUTOMATED_APPROVAL).lower()},
                )
            )
        return NominationResult(nomination, "manual_review_needed", issues, record, stages)

    stages.append(
        _stage(
            "automated_approval",
            "Automated approval gate",
            "passed",
            "Automated approval is enabled and all evidence checks passed.",
            details={"allow_automated_approval": str(ALLOW_AUTOMATED_APPROVAL).lower()},
        )
    )
    return NominationResult(nomination, "approved", record=record, stage_checks=stages)
