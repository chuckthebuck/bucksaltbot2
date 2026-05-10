from __future__ import annotations

import pytest
from datetime import date

from modules.four_award.replay import ReplayFailure, run_replay_case


def test_replay_matches_expected_successful_review():
    four_before = """== Current nominations ==
=== Example article ===
{{Four Award Nomination
 | article = Example article
 | dyknom = Template:Did you know nominations/Example article
 | user = Example
}}
"""
    records_before = """== Four Awards ==
{| class="wikitable"
! User
! Article
! Award date
! Creation date
! DYK date
! GA date
! FA date
|}
"""
    talk_before = """{{Article history
|action1=DYK
|action1date=2020-01-07
|action1link=[[Template:Did you know nominations/Example article]]
|action2=GAN
|action2date=2020-02-01
|action2link=[[Talk:Example article/GA1]]
|action3=FAC
|action3date=2020-03-01
|action3result=promoted
|action3link=[[Wikipedia:Featured article candidates/Example article/archive1]]
|currentstatus=FA
}}
"""
    case = {
        "settings": {"allow_automated_approval": True},
        "pages": {
            "Wikipedia:Four Award": {
                "before_text": four_before,
                "expected_text": "== Current nominations ==\n\n",
            },
            "Wikipedia:Four Award/Records": {
                "before_text": records_before,
                "expected_text": records_before.replace(
                    "|}\n",
                    "|-\n"
                    f"| [[User:Example|Example]] || [[Example article]] || {{{{dts|{date.today().year}|{date.today().month:02d}|{date.today().day:02d}}}}} || "
                    "{{dts|2020|01|01}} || {{dts|2020|01|07}} || {{dts|2020|02|01}} || {{dts|2020|03|01}}\n"
                    "|}\n\n",
                ),
            },
            "Talk:Example article": {
                "before_text": talk_before,
                "expected_text": talk_before.replace("}}\n", "|four=yes\n}}\n"),
            },
            "User talk:Example": {
                "before_text": "",
                "expected_text": "\n\n== Four Award ==\n<!-- FourAwardBot:approved:Example_article -->\n{{subst:Four Award Message|Example article}}\n",
            },
            "Template:Did you know nominations/Example article": {
                "before_text": "[[User:Example|Example]]",
                "expected_text": "[[User:Example|Example]]",
            },
            "Talk:Example article/GA1": {
                "before_text": "[[User:Example|Example]]",
                "expected_text": "[[User:Example|Example]]",
            },
            "Wikipedia:Featured article candidates/Example article/archive1": {
                "before_text": "[[User:Example|Example]]",
                "expected_text": "[[User:Example|Example]]",
            },
        },
        "existing_pages": ["Example article"],
        "page_creation": {"Example article": {"user": "Example", "date": "2020-01-01"}},
        "revision_users": {
            "Example article": ["Example"],
            "Template:Did you know nominations/Example article": ["Example"],
            "Talk:Example article/GA1": ["Example"],
            "Wikipedia:Featured article candidates/Example article/archive1": ["Example"],
        },
        "expected_result": {"approved": 1, "failed": 0, "manual": 0},
    }

    payload = run_replay_case(case)

    assert [edit["title"] for edit in payload["edits"]] == [
        "Wikipedia:Four Award",
        "Talk:Example article",
        "User talk:Example",
        "Wikipedia:Four Award/Records",
    ]


def _successful_review_case() -> dict:
    four_text = """== Current nominations ==
=== Example article ===
{{Four Award Nomination
 | article = Example article
 | dyknom = Template:Did you know nominations/Example article
 | user = Example
}}
"""
    talk_text = """{{Article history
|action1=DYK
|action1date=2020-01-07
|action1link=[[Template:Did you know nominations/Example article]]
|action2=GAN
|action2date=2020-02-01
|action2link=[[Talk:Example article/GA1]]
|action3=FAC
|action3date=2020-03-01
|action3result=promoted
|action3link=[[Wikipedia:Featured article candidates/Example article/archive1]]
|currentstatus=FA
}}
"""
    return {
        "pages": {
            "Wikipedia:Four Award": {"before_text": four_text},
            "Wikipedia:Four Award/Records": {
                "before_text": "== Four Awards ==\n{| class=\"wikitable\"\n! User\n! Article\n|}\n"
            },
            "Talk:Example article": {"before_text": talk_text},
            "User talk:Example": {"before_text": ""},
            "Template:Did you know nominations/Example article": {
                "before_text": "[[User:Example|Example]]"
            },
            "Talk:Example article/GA1": {"before_text": "[[User:Example|Example]]"},
            "Wikipedia:Featured article candidates/Example article/archive1": {
                "before_text": "[[User:Example|Example]]"
            },
        },
        "existing_pages": ["Example article"],
        "page_creation": {"Example article": {"user": "Example", "date": "2020-01-01"}},
        "revision_users": {
            "Example article": ["Example"],
            "Template:Did you know nominations/Example article": ["Example"],
            "Talk:Example article/GA1": ["Example"],
            "Wikipedia:Featured article candidates/Example article/archive1": ["Example"],
        },
    }


def test_manual_review_report_explains_automated_approval_gate():
    case = _successful_review_case()
    case["settings"] = {"allow_automated_approval": False}
    case["expected_result"] = {"approved": 0, "failed": 0, "manual": 1}

    payload = run_replay_case(case)
    result = payload["result"]
    report = result["dry_run_report"]["wikitext"]

    assert result["reviews"][0]["issues"][-1]["code"] == "automated_approval_disabled"
    assert "=== Verification details ===" in report
    assert "Page creation / early edits" in report
    assert "DYK contribution" in report
    assert "GA contribution" in report
    assert "FA contribution" in report
    assert "Automated approval gate" in report
    assert "Automated approval is disabled by configuration" in report


def test_historical_payload_page_text_is_used_instead_of_live_four_award_page():
    case = _successful_review_case()
    historical_text = case["pages"]["Wikipedia:Four Award"]["before_text"]
    case["settings"] = {"allow_automated_approval": True}
    case["payload"] = {"four_page_text": historical_text}
    case["pages"]["Wikipedia:Four Award"]["before_text"] = "== Current nominations ==\n"
    case["expected_result"] = {"approved": 1, "failed": 0, "manual": 0}

    payload = run_replay_case(case)

    assert payload["result"]["reviews"][0]["article"] == "Example article"


def test_historical_payload_can_ignore_current_records_table():
    case = _successful_review_case()
    historical_text = case["pages"]["Wikipedia:Four Award"]["before_text"]
    case["settings"] = {"allow_automated_approval": True}
    case["payload"] = {
        "four_page_text": historical_text,
        "ignore_existing_records": True,
    }
    case["pages"]["Wikipedia:Four Award/Records"]["before_text"] = (
        "== Four Awards ==\n"
        "{| class=\"wikitable\"\n"
        "! User\n! Article\n"
        "|-\n"
        "| [[User:Example|Example]] || [[Example article]]\n"
        "|}\n"
    )
    case["expected_result"] = {"approved": 1, "failed": 0, "manual": 0}

    payload = run_replay_case(case)
    stages = payload["result"]["reviews"][0]["stage_checks"]

    assert any(
        stage["key"] == "duplicate_record" and stage["status"] == "skipped"
        for stage in stages
    )


def test_placeholder_user_is_not_treated_as_real_user():
    case = _successful_review_case()
    case["settings"] = {"allow_automated_approval": True}
    case["pages"]["Wikipedia:Four Award"]["before_text"] = """== Current nominations ==
=== Diaspora Revolt ===
{{Four Award Nomination
 | article = Diaspora Revolt
 | user = USERNAME(S) (remove if you are nominating yourself)
}}
"""
    case["pages"]["Talk:Diaspora Revolt"] = {"before_text": ""}
    case["existing_pages"] = ["Diaspora Revolt"]
    case["page_creation"] = {"Diaspora Revolt": {"user": "RealUser", "date": "2020-01-01"}}
    case["revision_users"] = {"Diaspora Revolt": ["RealUser"]}
    case["expected_result"] = {"approved": 0, "failed": 0, "manual": 1}

    payload = run_replay_case(case)

    assert payload["result"]["reviews"][0]["users"] == []
    assert payload["edits"] == [
        {
            "title": "Wikipedia:Four Award",
            "summary": "Reply to Four Award nomination for [[Diaspora Revolt]]",
        }
    ]


def test_one_line_article_history_params_are_split_cleanly():
    case = _successful_review_case()
    case["settings"] = {"allow_automated_approval": True}
    case["pages"]["Talk:Example article"]["before_text"] = (
        "{{Article history|action1=DYK|action1date=2 May 2018"
        "|dykentry=... that the example exists?|dyknom=Template:Did you know nominations/Example article"
        "|action1link=[[Template:Did you know nominations/Example article]]"
        "|action2=GAN|action2date=2 January 2024|action2link=[[/GA1]]"
        "|action3=FAC|action3date=03 April 2026|action3result=promoted"
        "|action3link=[[Wikipedia:Featured article candidates/Example article/archive1]]"
        "|currentstatus=FA}}\n"
    )
    case["page_creation"] = {"Example article": {"user": "Example", "date": "2018-03-29"}}
    case["revision_users"]["Example article"] = ["Example"]
    case["revision_users"]["Talk:Example article/GA1"] = ["Example"]
    case["expected_result"] = {"approved": 1, "failed": 0, "manual": 0}

    payload = run_replay_case(case)
    review = payload["result"]["reviews"][0]
    report = payload["result"]["dry_run_report"]["wikitext"]

    assert review["stage_checks"][4]["details"]["dyk_date"] == "2 May 2018"
    assert "dykentry=" not in review["stage_checks"][4]["details"]["dyk_date"]
    assert "Pages: [[Example article]]; [[Talk:Example article/GA1]]" in report


def test_manual_nomination_links_work_without_article_history_template():
    four_text = """== Current nominations ==
===={{user|Crisco 1492}}====
Article: '''[[Murder of Wang Lianying]] ([[Talk:Murder of Wang Lianying|talk]], [{{fullurl:Murder of Wang Lianying|action=history}} history])'''
:[[File:Symbol draft class.svg|25px]] '''New article''': [{{fullurl:Murder of Wang Lianying|dir=prev&limit=1&action=history}} diff for creation]
:[[File:Symbol question.svg|25px]] '''DYK''': [[Wikipedia:Did you know archive/2024/November#23 November 2024]] and [[Template:Did you know nominations/Murder of Wang Lianying|nomination]]
:[[File:Symbol support vote.svg|25px]] '''GA''': [[Talk:Murder of Wang Lianying/GA1]]
:[[File:Symbol star FA gold.svg|25px]] '''FA''': [[Wikipedia:Featured article candidates/Murder of Wang Lianying/archive1]]
:: &nbsp;—&nbsp;[[User:Crisco 1492|Chris Woodrich]] ([[User talk:Crisco 1492|talk]]) 23:22, 4 May 2026 (UTC)
"""
    case = {
        "settings": {"allow_automated_approval": True},
        "pages": {
            "Wikipedia:Four Award": {"before_text": four_text},
            "Wikipedia:Four Award/Records": {
                "before_text": "== Four Awards ==\n{| class=\"wikitable\"\n! User\n! Article\n|}\n"
            },
            "Talk:Murder of Wang Lianying": {"before_text": ""},
            "User talk:Crisco 1492": {"before_text": ""},
            "Template:Did you know nominations/Murder of Wang Lianying": {
                "before_text": "[[User:Crisco 1492|Crisco 1492]]"
            },
            "Talk:Murder of Wang Lianying/GA1": {
                "before_text": (
                    "[[User:Crisco 1492|Crisco 1492]]\n"
                    "Article promoted by [[User:ChristieBot|ChristieBot]] 6 May 2025 (UTC)"
                )
            },
            "Wikipedia:Featured article candidates/Murder of Wang Lianying/archive1": {
                "before_text": (
                    "[[User:Crisco 1492|Crisco 1492]]\n"
                    "Promoted by [[User:FACBot|FACBot]] 23:06, 4 May 2026 (UTC)"
                )
            },
        },
        "existing_pages": ["Murder of Wang Lianying"],
        "page_creation": {
            "Murder of Wang Lianying": {"user": "Crisco 1492", "date": "2024-01-01"}
        },
        "revision_users": {
            "Murder of Wang Lianying": ["Crisco 1492"],
            "Template:Did you know nominations/Murder of Wang Lianying": ["Crisco 1492"],
            "Talk:Murder of Wang Lianying/GA1": ["Crisco 1492"],
            "Wikipedia:Featured article candidates/Murder of Wang Lianying/archive1": ["Crisco 1492"],
        },
        "latest_revision_dates": {
            "Talk:Murder of Wang Lianying/GA1": "2025-05-06",
            "Wikipedia:Featured article candidates/Murder of Wang Lianying/archive1": "2026-05-04",
        },
        "expected_result": {"approved": 1, "failed": 0, "manual": 0},
    }

    payload = run_replay_case(case)
    stages = payload["result"]["reviews"][0]["stage_checks"]
    milestone_details = next(
        stage["details"]
        for stage in stages
        if stage["key"] == "milestone_dates"
    )

    assert any(
        stage["key"] == "article_history" and stage["status"] == "skipped"
        for stage in stages
    )
    assert any(
        stage["key"] == "fa_status" and stage["status"] == "passed"
        for stage in stages
    )
    assert milestone_details["dyk_date"] == "23 November 2024"
    assert milestone_details["ga_date"] == "2025-05-06"
    assert milestone_details["fa_date"] == "2026-05-04"


def test_replay_failure_shows_diff():
    case = {
        "pages": {
            "Wikipedia:Four Award": {
                "before_text": "== Current nominations ==\n",
                "expected_text": "wrong\n",
            }
        }
    }

    with pytest.raises(ReplayFailure) as excinfo:
        run_replay_case(case)

    assert "expected/Wikipedia:Four Award" in str(excinfo.value)


def test_historic_great_mecca_feast_replay_fixture_loads():
    from modules.four_award.replay import load_case

    case = load_case("tests/fixtures/four_award_replay_1345035310_great_mecca_feast.json")

    assert case["pages"]["Wikipedia:Four Award"]["before_revid"] == 1345035310
    assert case["pages"]["Wikipedia:Four Award/Records"]["expected_revid"] == 1346457952
