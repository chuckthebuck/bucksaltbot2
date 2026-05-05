"""Tests for framework authorization grant expansion."""

from unittest.mock import patch


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_auto_grants_accept_project_groups_for_any_project():
    from router import authz

    config = {
        "ROLE_GRANTS_JSON": {
            "project:enwiki:extendedconfirmed": ["module:four_award:access"]
        },
        "CHUCKBOT_GROUPS_JSON": {},
    }

    with patch(
        "router.authz.get_project_user_groups",
        return_value=["extendedconfirmed"],
    ):
        grants = authz._expand_all_grants(config, "Example")

    assert "module:four_award:access" in grants


def test_auto_grants_accept_global_groups():
    from router import authz

    config = {
        "ROLE_GRANTS_JSON": {
            "global:global-sysop": ["group:module_4award_manager"]
        },
        "CHUCKBOT_GROUPS_JSON": {
            "module_4award_manager": [
                "module:four_award:manage",
                "module:four_award:run_jobs",
            ]
        },
    }

    with patch("router.authz.get_user_global_groups", return_value=["global-sysop"]):
        grants = authz._expand_all_grants(config, "Example")

    assert "module:four_award:manage" in grants
    assert "module:four_award:run_jobs" in grants


def test_module_specific_manage_does_not_grant_other_modules():
    from router import authz

    config = {
        "ROLLBACK_CONTROL_JSON": {
            "Example": ["module:four_award:manage"]
        },
        "ROLE_GRANTS_JSON": {},
        "CHUCKBOT_GROUPS_JSON": {},
    }

    with patch("router.authz._effective_runtime_authz_config", return_value=config):
        assert authz.user_has_module_right("Example", "four_award", "manage")
        assert not authz.user_has_module_right("Example", "rollback", "manage")


def test_module_specific_estop_is_a_module_scoped_right():
    from router import authz

    config = {
        "ROLLBACK_CONTROL_JSON": {
            "Example": ["module:four_award:estop"]
        },
        "ROLE_GRANTS_JSON": {},
        "CHUCKBOT_GROUPS_JSON": {},
    }

    with patch("router.authz._effective_runtime_authz_config", return_value=config):
        assert authz.user_has_module_right("Example", "four_award", "estop")
        assert not authz.user_has_module_right("Example", "rollback", "estop")


def test_mediawiki_username_normalization_preserves_case_after_first_character():
    from router import authz

    assert authz._normalize_username("alachuckthebuck") == "Alachuckthebuck"
    assert authz._normalize_username("AlaChuckthebuck") == "AlaChuckthebuck"
    assert authz._normalize_username("The_Squirrel_Conspiracy") == "The Squirrel Conspiracy"


def test_user_grants_do_not_collapse_distinct_mediawiki_usernames():
    from router import authz

    config = {
        "ROLLBACK_CONTROL_JSON": {
            "Alachuckthebuck": ["module:four_award:manage"],
            "AlaChuckthebuck": ["module:rollback:manage"],
        },
        "ROLE_GRANTS_JSON": {},
        "CHUCKBOT_GROUPS_JSON": {},
    }

    assert authz._expand_user_grants(config, "Alachuckthebuck") == {
        "module:four_award:manage"
    }
    assert authz._expand_user_grants(config, "AlaChuckthebuck") == {
        "module:rollback:manage"
    }


def test_project_userright_group_options_come_from_siteinfo():
    from router import authz

    authz._group_cache.clear()

    with patch("router.authz.requests.get") as get:
        get.return_value = _FakeResponse(
            {
                "query": {
                    "usergroups": [
                        {"name": "sysop"},
                        {"name": "extendedconfirmed"},
                    ]
                }
            }
        )

        assert authz.get_project_userright_groups("enwiki", force_refresh=True) == [
            "extendedconfirmed",
            "sysop",
        ]

    _, kwargs = get.call_args
    assert kwargs["params"]["siprop"] == "usergroups"


def test_global_user_groups_use_globaluserinfo_and_preserve_spaces():
    from router import authz

    authz._group_cache.clear()

    with patch("router.authz.requests.get") as get:
        get.return_value = _FakeResponse(
            {
                "query": {
                    "globaluserinfo": {
                        "groups": ["global-sysop", "global-interface-editor"]
                    }
                }
            }
        )

        assert authz.get_user_global_groups(
            "The_Squirrel_Conspiracy", force_refresh=True
        ) == ["global-interface-editor", "global-sysop"]

    _, kwargs = get.call_args
    assert kwargs["params"]["meta"] == "globaluserinfo"
    assert kwargs["params"]["guiuser"] == "The Squirrel Conspiracy"


def test_global_userright_group_options_come_from_centralauth():
    from router import authz

    authz._group_cache.clear()

    with patch("router.authz.requests.get") as get:
        get.return_value = _FakeResponse(
            {
                "query": {
                    "globalgroups": [
                        {"name": "global-sysop"},
                        {"name": "steward"},
                    ]
                }
            }
        )

        assert authz.get_global_userright_groups(force_refresh=True) == [
            "global-sysop",
            "steward",
        ]

    _, kwargs = get.call_args
    assert kwargs["params"]["list"] == "globalgroups"
