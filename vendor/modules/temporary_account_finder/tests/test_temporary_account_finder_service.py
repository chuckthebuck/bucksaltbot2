from __future__ import annotations

from urllib.parse import unquote

import pytest

from temporary_account_finder.service import (
    FinderError,
    check_access,
    find_connected_accounts,
    parse_seed_accounts,
    resolve_wiki,
)


ACCESS_TOKEN = {"key": "access-key", "secret": "access-secret"}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeTransport:
    def __init__(
        self,
        *,
        rights=None,
        username="Example",
        blocked=False,
        connected=None,
        ips=None,
    ):
        self.rights = rights or ["checkuser-temporary-account"]
        self.username = username
        self.blocked = blocked
        self.connected = connected or {}
        self.ips = ips or {}
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        data = kwargs.get("data") or {}
        if data.get("meta") == "userinfo":
            userinfo = {"name": self.username, "rights": self.rights}
            if self.blocked:
                userinfo.update({"blockid": 99, "blockedby": "Admin"})
            return FakeResponse({"query": {"userinfo": userinfo}})
        if data.get("meta") == "tokens":
            return FakeResponse({"query": {"tokens": {"csrftoken": "csrf-token+\\"}}})
        if "/connectedtemporaryaccounts/" in url:
            seed = unquote(url.rsplit("/", 1)[1]).replace("_", " ")
            response = self.connected.get(
                seed, {"connectedAccounts": [seed], "ipsUsedCount": 1}
            )
            if isinstance(response, tuple):
                return FakeResponse(response[1], response[0])
            return FakeResponse(response)
        if "/temporaryaccount/" in url:
            seed = unquote(url.rsplit("/", 1)[1]).replace("_", " ")
            response = self.ips.get(seed, {"ips": []})
            if isinstance(response, tuple):
                return FakeResponse(response[1], response[0])
            return FakeResponse(response)
        raise AssertionError(f"Unexpected request: {url} {kwargs}")


@pytest.fixture(autouse=True)
def oauth_environment(monkeypatch):
    monkeypatch.setenv("USER_OAUTH_CONSUMER_KEY", "consumer-key")
    monkeypatch.setenv("USER_OAUTH_CONSUMER_SECRET", "consumer-secret")


def test_resolve_wiki_supports_primary_aliases_and_public_projects():
    assert resolve_wiki("meta").host == "meta.wikimedia.org"
    assert resolve_wiki("commonswiki").host == "commons.wikimedia.org"
    assert resolve_wiki("enwiki").host == "en.wikipedia.org"
    assert resolve_wiki("dewiki").host == "de.wikipedia.org"
    assert resolve_wiki("https://www.wikidata.org/").host == "www.wikidata.org"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "example.com",
        "http://meta.wikimedia.org",
        "https://meta.wikimedia.org/wiki/Test",
        "https://meta.wikimedia.org:not-a-port",
    ],
)
def test_resolve_wiki_rejects_non_project_targets(value):
    with pytest.raises(FinderError):
        resolve_wiki(value)


def test_parse_seed_accounts_accepts_pasted_forms_and_deduplicates():
    accounts = parse_seed_accounts(
        "~2026-100\nUser:~2026-200\n"
        "https://en.wikipedia.org/wiki/Special:Contributions/~2026-100"
    )
    assert accounts == ["~2026-100", "~2026-200"]


def test_parse_seed_accounts_rejects_registered_names():
    with pytest.raises(FinderError, match="Only temporary-account names"):
        parse_seed_accounts("Example\n~2026-100")


def test_parse_seed_accounts_rejects_object_shape():
    with pytest.raises(FinderError, match="accounts must be"):
        parse_seed_accounts({"~2026-100": True})


def test_check_access_reports_live_selected_wiki_right():
    payload = check_access(
        "commons",
        expected_username="Example",
        access_token=ACCESS_TOKEN,
        transport=FakeTransport(),
    )
    assert payload["eligible"] is True
    assert payload["wiki"]["host"] == "commons.wikimedia.org"
    assert payload["reveal_rights"] == ["checkuser-temporary-account"]


def test_check_access_denies_sitewide_blocked_actor():
    payload = check_access(
        "enwiki",
        expected_username="Example",
        access_token=ACCESS_TOKEN,
        transport=FakeTransport(blocked=True),
    )
    assert payload["eligible"] is False
    assert payload["blocked"] is True


def test_search_unions_results_without_returning_ip_addresses():
    transport = FakeTransport(
        connected={
            "~2026-100": {
                "connectedAccounts": ["~2026-100", "~2026-300"],
                "ipsUsedCount": 2,
            },
            "~2026-200": {
                "connectedAccounts": ["~2026-200", "~2026-300"],
                "ipsUsedCount": 1,
            },
        }
    )
    payload = find_connected_accounts(
        "meta",
        ["~2026-100", "~2026-200"],
        expected_username="Example",
        access_token=ACCESS_TOKEN,
        transport=transport,
    )

    assert payload["combined_accounts"] == ["~2026-100", "~2026-300", "~2026-200"]
    assert payload["combined_count"] == 3
    assert payload["complete"] is True
    assert payload["privacy"]["contains_ip_addresses"] is False
    rest_calls = [
        call for call in transport.calls if "/connectedtemporaryaccounts/" in call[0]
    ]
    assert len(rest_calls) == 2
    assert all(call[1]["json"] == {"token": "csrf-token+\\"} for call in rest_calls)
    assert "192.0.2.1" not in str(payload)


def test_search_can_return_ips_ephemerally_without_server_storage():
    transport = FakeTransport(
        connected={
            "~2026-100": {
                "connectedAccounts": ["~2026-100", "~2026-300"],
                "ipsUsedCount": 2,
            }
        },
        ips={"~2026-100": {"ips": ["192.0.2.1", "2001:0db8::1"]}},
    )
    payload = find_connected_accounts(
        "meta",
        "~2026-100",
        expected_username="Example",
        access_token=ACCESS_TOKEN,
        include_ips=True,
        transport=transport,
    )

    assert payload["results"][0]["ip_addresses"] == ["192.0.2.1", "2001:db8::1"]
    assert payload["privacy"] == {
        "contains_ip_addresses": True,
        "ip_storage": "none",
        "ip_retention_days": 0,
        "authorization_checked_by": ["chuckbot", "meta.wikimedia.org"],
    }
    assert (
        len([call for call in transport.calls if "/temporaryaccount/" in call[0]]) == 1
    )


def test_search_rejects_invalid_ip_from_upstream_as_partial_failure():
    transport = FakeTransport(ips={"~2026-100": {"ips": ["not-an-ip"]}})
    payload = find_connected_accounts(
        "meta",
        "~2026-100",
        expected_username="Example",
        access_token=ACCESS_TOKEN,
        include_ips=True,
        transport=transport,
    )
    assert payload["complete"] is False
    assert payload["results"] == []
    assert payload["errors"][0]["seed"] == "~2026-100"


def test_search_denies_missing_reveal_right_before_private_lookup():
    transport = FakeTransport(rights=["read"])
    with pytest.raises(FinderError) as exc_info:
        find_connected_accounts(
            "meta",
            "~2026-100",
            expected_username="Example",
            access_token=ACCESS_TOKEN,
            transport=transport,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "taiv_required"
    assert not any(
        "/connectedtemporaryaccounts/" in call[0] for call in transport.calls
    )


def test_search_rejects_oauth_actor_mismatch():
    with pytest.raises(FinderError) as exc_info:
        find_connected_accounts(
            "meta",
            "~2026-100",
            expected_username="Different user",
            access_token=ACCESS_TOKEN,
            transport=FakeTransport(username="Example"),
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "oauth_mismatch"


def test_search_returns_safe_partial_error_for_one_bad_seed():
    transport = FakeTransport(
        connected={
            "~2026-100": {"connectedAccounts": ["~2026-100"], "ipsUsedCount": 1},
            "~2026-200": {"unexpected": "shape"},
        }
    )
    payload = find_connected_accounts(
        "commons",
        "~2026-100\n~2026-200",
        expected_username="Example",
        access_token=ACCESS_TOKEN,
        transport=transport,
    )
    assert payload["complete"] is False
    assert payload["combined_accounts"] == ["~2026-100"]
    assert payload["errors"][0]["seed"] == "~2026-200"


def test_rest_permission_failure_is_not_returned_as_partial_success():
    transport = FakeTransport(
        connected={
            "~2026-100": (403, {"message": "checkuser-rest-access-denied"}),
        }
    )
    with pytest.raises(FinderError) as exc_info:
        find_connected_accounts(
            "meta",
            "~2026-100",
            expected_username="Example",
            access_token=ACCESS_TOKEN,
            transport=transport,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "taiv_required"
