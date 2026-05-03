"""Tests for framework authorization grant expansion."""

from unittest.mock import patch


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
            "example": ["module:four_award:manage"]
        },
        "ROLE_GRANTS_JSON": {},
        "CHUCKBOT_GROUPS_JSON": {},
    }

    with patch("router.authz._effective_runtime_authz_config", return_value=config):
        assert authz.user_has_module_right("Example", "four_award", "manage")
        assert not authz.user_has_module_right("Example", "rollback", "manage")
