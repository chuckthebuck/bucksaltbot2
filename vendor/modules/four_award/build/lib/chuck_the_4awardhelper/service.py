from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List

from . import actions, config, parser, records, replies, reviewer, util, wiki
from .config import ENABLED, MAX_NOMINATIONS_PER_RUN
from .parser import parse_nominations
from .reviewer import review_nomination
from .records import sync_records_table
from .replies import reply_result
from .actions import remove_nomination, set_article_history_four
from .models import FourAwardRecord, NominationResult, VerificationStage


def _approved_records(results: List[NominationResult]) -> List[FourAwardRecord]:
    records: List[FourAwardRecord] = []
    for result in results:
        if not result.record:
            continue
        for user in result.nomination.users:
            records.append(
                FourAwardRecord(
                    user=user,
                    article=result.record.article,
                    award_date=result.record.award_date,
                    creation_date=result.record.creation_date,
                    dyk_date=result.record.dyk_date,
                    ga_date=result.record.ga_date,
                    fa_date=result.record.fa_date,
                )
            )
    return records


def _should_mark_article_history_no(result: NominationResult) -> bool:
    skip_codes = {"duplicate_record", "missing_article", "missing_article_page"}
    return not any(issue.code in skip_codes for issue in result.issues)


def _config_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def _apply_runtime_config(ctx: Any | None) -> None:
    global ENABLED, MAX_NOMINATIONS_PER_RUN

    if ctx is None or not hasattr(ctx, "config"):
        return

    cfg = ctx.config
    get = cfg.get if hasattr(cfg, "get") else lambda key, default=None: default

    wiki_code = str(get("wiki_code", config.WIKI_CODE) or config.WIKI_CODE).strip()
    wiki_family = str(get("wiki_family", config.WIKI_FAMILY) or config.WIKI_FAMILY).strip()
    wiki_api_url = str(get("wiki_api_url", "") or "").strip()
    if not wiki_api_url and wiki_family == "wikipedia":
        wiki_api_url = f"https://{wiki_code}.wikipedia.org/w/api.php"

    dry_run = _config_bool(get("dry_run", config.DRY_RUN), config.DRY_RUN)
    enabled = _config_bool(get("enabled", ENABLED), ENABLED)

    ENABLED = enabled
    MAX_NOMINATIONS_PER_RUN = int(
        get("max_nominations_per_run", MAX_NOMINATIONS_PER_RUN)
        or MAX_NOMINATIONS_PER_RUN
    )

    config.WIKI_CODE = wiki_code
    config.WIKI_FAMILY = wiki_family
    if wiki_api_url:
        config.WIKI_API_URL = wiki_api_url
    config.DRY_RUN = dry_run
    config.ENABLED = enabled
    config.MAX_NOMINATIONS_PER_RUN = MAX_NOMINATIONS_PER_RUN

    if get("four_page") is not None:
        config.FOUR_PAGE = str(get("four_page")).strip() or config.FOUR_PAGE
    if get("records_page") is not None:
        config.RECORDS_PAGE = str(get("records_page")).strip() or config.RECORDS_PAGE
    if get("leaderboard_page") is not None:
        config.LEADERBOARD_PAGE = str(get("leaderboard_page")).strip() or config.LEADERBOARD_PAGE

    parser.FOUR_PAGE = config.FOUR_PAGE
    actions.FOUR_PAGE = config.FOUR_PAGE
    replies.FOUR_PAGE = config.FOUR_PAGE
    reviewer.RECORDS_PAGE = config.RECORDS_PAGE
    records.RECORDS_PAGE = config.RECORDS_PAGE

    actions.ENABLE_ARTICLE_HISTORY = _config_bool(
        get("enable_article_history", config.ENABLE_ARTICLE_HISTORY),
        config.ENABLE_ARTICLE_HISTORY,
    )
    actions.ENABLE_REMOVAL = _config_bool(
        get("enable_removal", config.ENABLE_REMOVAL),
        config.ENABLE_REMOVAL,
    )
    records.ENABLE_RECORDS = _config_bool(
        get("enable_records", config.ENABLE_RECORDS),
        config.ENABLE_RECORDS,
    )
    replies.ENABLE_REPLIES = _config_bool(
        get("enable_replies", config.ENABLE_REPLIES),
        config.ENABLE_REPLIES,
    )
    replies.ENABLE_TALK_NOTICES = _config_bool(
        get("enable_talk_notices", config.ENABLE_TALK_NOTICES),
        config.ENABLE_TALK_NOTICES,
    )
    reviewer.ALLOW_AUTOMATED_APPROVAL = _config_bool(
        get("allow_automated_approval", config.ALLOW_AUTOMATED_APPROVAL),
        config.ALLOW_AUTOMATED_APPROVAL,
    )
    config.IGNORE_EXISTING_RECORDS = _config_bool(
        get("ignore_existing_records", config.IGNORE_EXISTING_RECORDS),
        config.IGNORE_EXISTING_RECORDS,
    )
    reviewer.IGNORE_EXISTING_RECORDS = config.IGNORE_EXISTING_RECORDS

    if get("award_date_override") is not None:
        config.AWARD_DATE_OVERRIDE = str(get("award_date_override") or "").strip() or None
        util.AWARD_DATE_OVERRIDE = config.AWARD_DATE_OVERRIDE
    if get("dry_run_report_page") is not None:
        config.DRY_RUN_REPORT_PAGE = str(get("dry_run_report_page") or "").strip()
    config.PUBLISH_DRY_RUN_REPORT = _config_bool(
        get("publish_dry_run_report", config.PUBLISH_DRY_RUN_REPORT),
        config.PUBLISH_DRY_RUN_REPORT,
    )

    wiki.configure_runtime(
        wiki_code=wiki_code,
        wiki_family=wiki_family,
        wiki_api_url=wiki_api_url,
        dry_run=dry_run,
    )


def run_four_award_sync(ctx: Any | None = None, payload: dict[str, Any] | None = None):
    _apply_runtime_config(ctx)
    wiki.reset_dry_run_edits()
    payload = payload or {}
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not ENABLED:
        return {
            "status": "disabled",
            "run_kind": "disabled",
            "has_nominations": False,
            "nomination_count": 0,
            "started_at": started_at,
        }

    source_page_text = payload.get("four_page_text") or payload.get("page_text")
    previous_ignore_existing_records = reviewer.IGNORE_EXISTING_RECORDS
    if payload.get("ignore_existing_records") is not None:
        reviewer.IGNORE_EXISTING_RECORDS = _config_bool(
            payload.get("ignore_existing_records"),
            reviewer.IGNORE_EXISTING_RECORDS,
        )
    nominations = parse_nominations(str(source_page_text) if source_page_text is not None else None)
    nomination_count = len(nominations)

    if nomination_count == 0:
        return {
            "status": "ok",
            "run_kind": "empty",
            "has_nominations": False,
            "nomination_count": 0,
            "dry_run": bool(config.DRY_RUN),
            "started_at": started_at,
        }

    approved: List[NominationResult] = []
    failed: List[NominationResult] = []
    manual: List[NominationResult] = []

    try:
        for nom in nominations[:MAX_NOMINATIONS_PER_RUN]:
            result = review_nomination(nom)

            if result.status == "approved":
                approved.append(result)
                remove_nomination(nom)
                set_article_history_four(nom.article, "yes")
                reply_result(nom, result)

            elif result.status == "failed_to_verify":
                failed.append(result)
                remove_nomination(nom)
                if _should_mark_article_history_no(result):
                    set_article_history_four(nom.article, "no")
                reply_result(nom, result)

            else:
                manual.append(result)
                reply_result(nom, result)
    finally:
        reviewer.IGNORE_EXISTING_RECORDS = previous_ignore_existing_records

    if approved:
        sync_records_table(_approved_records(approved))

    dry_run_edits = wiki.get_dry_run_edits()
    report_text = _dry_run_report_wikitext(dry_run_edits, approved, failed, manual)
    report_page = None
    if (
        config.DRY_RUN
        and config.PUBLISH_DRY_RUN_REPORT
        and config.DRY_RUN_REPORT_PAGE
        and dry_run_edits
    ):
        report_result = wiki.publish_dry_run_report(config.DRY_RUN_REPORT_PAGE, report_text)
        report_page = {
            "title": report_result.title,
            "summary": report_result.summary,
            "saved": report_result.saved,
        }

    return {
        "status": "ok",
        "run_kind": "reviewed",
        "has_nominations": True,
        "nomination_count": nomination_count,
        "processed_count": len(approved) + len(failed) + len(manual),
        "approved": len(approved),
        "failed": len(failed),
        "manual": len(manual),
        "reviews": _review_payloads(approved + failed + manual),
        "dry_run": bool(config.DRY_RUN),
        "dry_run_edits": dry_run_edits,
        "dry_run_report": {
            "wikitext": report_text,
            "published": report_page,
        },
    }


def _stage_payload(stage: VerificationStage) -> dict[str, object]:
    return {
        "key": stage.key,
        "label": stage.label,
        "status": stage.status,
        "reason": stage.reason,
        "expected_users": stage.expected_users,
        "evidence_users": stage.evidence_users,
        "pages": stage.pages,
        "start": stage.start,
        "end": stage.end,
        "details": stage.details,
    }


def _review_payloads(results: list[NominationResult]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for result in results:
        payloads.append(
            {
                "status": result.status,
                "article": result.nomination.article,
                "users": result.nomination.users,
                "issues": [
                    {"code": issue.code, "reason": issue.reason}
                    for issue in result.issues
                ],
                "stage_checks": [_stage_payload(stage) for stage in result.stage_checks],
            }
        )
    return payloads


def _result_rows(label: str, results: list[NominationResult]) -> list[str]:
    rows = []
    for result in results:
        issue_text = "; ".join(issue.reason for issue in result.issues) or ""
        rows.append(
            "|-\n"
            f"| {_table_cell(label)}\n"
            f"| [[{result.nomination.article}]]\n"
            f"| {_table_cell(', '.join(result.nomination.users))}\n"
            f"| {_table_cell(issue_text)}"
        )
    return rows


def _table_cell(value: object) -> str:
    return str(value or "").replace("|", "{{!}}").replace("\n", "<br>")


def _dry_run_report_wikitext(
    dry_run_edits: list[dict[str, object]],
    approved: list[NominationResult],
    failed: list[NominationResult],
    manual: list[NominationResult],
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "== Four Award dry-run report ==",
        f"Generated at {generated_at}. This is a dry-run preview; normal target pages were not edited.",
        "",
        "=== Review results ===",
        '{| class="wikitable sortable"',
        "! Result !! Article !! Users !! Notes",
    ]
    result_rows = (
        _result_rows("Approved", approved)
        + _result_rows("Failed", failed)
        + _result_rows("Manual review", manual)
    )
    lines.extend(result_rows or ["|-\n| colspan=\"4\" | No nominations were reviewed."])
    lines.extend(
        [
            "|}",
            "",
            "=== Proposed edits ===",
            '{| class="wikitable sortable"',
            "! Page !! Summary !! Size change",
        ]
    )
    for edit in dry_run_edits:
        title = str(edit.get("title") or "")
        summary = str(edit.get("summary") or "")
        delta = int(edit.get("delta_chars") or 0)
        lines.append(f"|-\n| [[{title}]]\n| {_table_cell(summary)}\n| {delta:+d} chars")
    if not dry_run_edits:
        lines.append("|-\n| colspan=\"3\" | No edits would be made.")
    lines.extend(["|}", ""])

    detail_rows = _verification_detail_rows(approved + failed + manual)
    if detail_rows:
        lines.extend(
            [
                "=== Verification details ===",
                '{| class="wikitable sortable"',
                "! Article !! Stage !! Status !! Evidence !! Notes",
            ]
        )
        lines.extend(detail_rows)
        lines.extend(["|}", ""])

    if dry_run_edits:
        lines.extend(["=== Diff previews ==="])
        for edit in dry_run_edits:
            title = str(edit.get("title") or "")
            diff = str(edit.get("diff") or "").strip()
            lines.extend(
                [
                    f"==== {title} ====",
                    "<syntaxhighlight lang=\"diff\">",
                    diff or "No text diff was captured.",
                    "</syntaxhighlight>",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _verification_detail_rows(results: list[NominationResult]) -> list[str]:
    rows: list[str] = []
    for result in results:
        article = result.nomination.article
        for stage in result.stage_checks:
            evidence_parts: list[str] = []
            if stage.expected_users:
                evidence_parts.append("Expected: " + ", ".join(stage.expected_users))
            if stage.evidence_users:
                evidence_parts.append("Found: " + ", ".join(stage.evidence_users))
            if stage.start or stage.end:
                evidence_parts.append(f"Window: {stage.start or '?'} to {stage.end or '?'}")
            if stage.pages:
                evidence_parts.append("Pages: " + "; ".join(f"[[{page}]]" for page in stage.pages))
            details = [f"{key}: {value}" for key, value in stage.details.items() if value]
            if details:
                evidence_parts.append("; ".join(details))

            rows.append(
                "|-\n"
                f"| [[{article}]]\n"
                f"| {_table_cell(stage.label)}\n"
                f"| {_table_cell(stage.status)}\n"
                f"| {_table_cell('<br>'.join(evidence_parts))}\n"
                f"| {_table_cell(stage.reason)}"
            )
    return rows
