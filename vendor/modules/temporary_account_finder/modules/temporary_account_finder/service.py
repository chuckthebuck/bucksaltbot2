"""Authorized Wikimedia connected-temporary-account lookups.

The selected wiki remains the policy authority. Chuckbot signs every request as
the browser-session user, verifies that user's effective reveal right, and then
uses CheckUser's connected-account endpoint. That endpoint performs its own
permission/block checks and access logging. Optional raw IP results remain
ephemeral and are never written by this module.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import ipaddress
import os
import re
from typing import Any, Iterable
from urllib.parse import quote, unquote, urlparse

import requests
from requests_oauthlib import OAuth1


MAX_SEED_ACCOUNTS = 50
MAX_WORKERS = 4
REVEAL_RIGHTS = {
    "checkuser-temporary-account",
    "checkuser-temporary-account-no-preference",
}

WIKI_ALIASES = {
    "meta": "meta.wikimedia.org",
    "metawiki": "meta.wikimedia.org",
    "commons": "commons.wikimedia.org",
    "commonswiki": "commons.wikimedia.org",
    "enwiki": "en.wikipedia.org",
    "wikidata": "www.wikidata.org",
    "wikidatawiki": "www.wikidata.org",
    "mediawiki": "www.mediawiki.org",
    "mediawikiwiki": "www.mediawiki.org",
}

WIKIMEDIA_PROJECT_SUFFIXES = (
    "mediawiki.org",
    "wikibooks.org",
    "wikidata.org",
    "wikifunctions.org",
    "wikimedia.org",
    "wikinews.org",
    "wikipedia.org",
    "wikiquote.org",
    "wikisource.org",
    "wikiversity.org",
    "wikivoyage.org",
    "wiktionary.org",
)


class FinderError(RuntimeError):
    """A user-safe lookup failure with an HTTP status for the module API."""

    def __init__(
        self, detail: str, status_code: int = 400, *, code: str = "invalid_request"
    ):
        """Preserve the safe detail, response status, and stable machine code."""
        self.detail = detail
        self.status_code = status_code
        self.code = code
        super().__init__(detail)


class UpstreamError(FinderError):
    """A selected-wiki request failed without exposing its private payload."""

    def __init__(
        self, detail: str, *, status_code: int = 502, code: str = "wiki_error"
    ):
        """Create a failure attributed to the selected Wikimedia wiki."""
        super().__init__(detail, status_code, code=code)


@dataclass(frozen=True)
class WikiTarget:
    """A validated public Wikimedia project endpoint."""

    host: str

    @property
    def api_url(self) -> str:
        """Return this wiki's MediaWiki Action API endpoint."""
        return f"https://{self.host}/w/api.php"

    @property
    def rest_url(self) -> str:
        """Return this wiki's MediaWiki REST entry point."""
        return f"https://{self.host}/w/rest.php"

    def as_dict(self) -> dict[str, str]:
        """Return the small public wiki description used by the UI."""
        return {"host": self.host, "url": f"https://{self.host}"}


def resolve_wiki(value: str) -> WikiTarget:
    """Resolve a common alias or a strictly allowlisted Wikimedia hostname."""
    raw = str(value or "").strip().lower()
    if not raw:
        raise FinderError("Choose a Wikimedia wiki.")

    host = WIKI_ALIASES.get(raw, raw)
    if "://" in host:
        parsed = urlparse(host)
        try:
            parsed_port = parsed.port
        except ValueError as exc:
            raise FinderError(
                "That is not a valid Wikimedia project hostname."
            ) from exc
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed_port
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise FinderError("Enter a Wikimedia project hostname, not a page URL.")
        host = parsed.hostname or ""

    # Common database-style language aliases, e.g. dewiki or pt_brwiki.
    language_match = re.fullmatch(r"([a-z][a-z0-9-]{0,19})wiki", host)
    if language_match:
        host = f"{language_match.group(1)}.wikipedia.org"

    host = host.rstrip(".")
    if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", host):
        raise FinderError("That is not a valid Wikimedia project hostname.")
    if not any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in WIKIMEDIA_PROJECT_SUFFIXES
    ):
        raise FinderError("Only public Wikimedia project wikis are supported.")

    return WikiTarget(host=host)


def _clean_account(value: Any) -> str:
    """Normalize one pasted contribution link, User prefix, or plain TA name."""
    account = str(value or "").strip()
    account = re.sub(r"^[*#-]\s+", "", account)

    if account[:2] == "[[" and account[-2:] == "]]":
        account = account[2:-2].split("|", 1)[0].strip()

    if account.lower().startswith(("http://", "https://")):
        parsed = urlparse(account)
        path = unquote(parsed.path)
        if "/Special:Contributions/" in path:
            account = path.rsplit("/Special:Contributions/", 1)[1]
        elif "/wiki/User:" in path:
            account = path.rsplit("/wiki/User:", 1)[1]

    account = unquote(account).replace("_", " ").strip()
    if account.lower().startswith("user:"):
        account = account[5:].strip()
    if account.lower().startswith("special:contributions/"):
        account = account.split("/", 1)[1].strip()

    return " ".join(account.split())


def parse_seed_accounts(value: str | Iterable[Any]) -> list[str]:
    """Parse, validate, and deduplicate a bounded list of temporary accounts."""
    if isinstance(value, str):
        raw_values: Iterable[Any] = re.split(r"[\n,;]+", value)
    elif isinstance(value, Iterable) and not isinstance(
        value, (bytes, bytearray, dict)
    ):
        raw_values = value
    else:
        raise FinderError("accounts must be a list or pasted text")

    accounts: list[str] = []
    seen: set[str] = set()
    invalid: list[str] = []
    for raw in raw_values:
        account = _clean_account(raw)
        if not account:
            continue
        # CheckUser is authoritative about the exact temporary-name format. This
        # local bound prevents arbitrary REST path use while allowing format
        # changes that retain MediaWiki's configured '~' prefix.
        if (
            not account.startswith("~")
            or len(account) > 255
            or any(char in account for char in "#[]{}|<>/\\")
        ):
            invalid.append(account)
            continue
        key = account.casefold()
        if key not in seen:
            seen.add(key)
            accounts.append(account)

    if invalid:
        preview = ", ".join(invalid[:3])
        suffix = "…" if len(invalid) > 3 else ""
        raise FinderError(
            f"Only temporary-account names are accepted: {preview}{suffix}"
        )
    if not accounts:
        raise FinderError("Enter at least one temporary-account name.")
    if len(accounts) > MAX_SEED_ACCOUNTS:
        raise FinderError(
            f"Enter no more than {MAX_SEED_ACCOUNTS} temporary accounts at once."
        )
    return accounts


def _token_part(payload: dict[str, Any], name: str) -> str:
    """Read one required session-token part or request reauthorization."""
    value = str(payload.get(name) or "").strip()
    if not value:
        raise FinderError(
            "Your Chuckbot OAuth session is incomplete. Sign out and authorize Chuckbot again.",
            401,
            code="oauth_required",
        )
    return value


@dataclass(frozen=True)
class OAuthCredentials:
    """The four OAuth 1.0a values needed to sign one wiki request."""

    consumer_key: str
    consumer_secret: str
    access_key: str
    access_secret: str

    @classmethod
    def from_session(cls, access_token: dict[str, Any] | None) -> "OAuthCredentials":
        """Combine configured consumer credentials with a user's session token."""
        consumer_key = str(os.environ.get("USER_OAUTH_CONSUMER_KEY") or "").strip()
        consumer_secret = str(
            os.environ.get("USER_OAUTH_CONSUMER_SECRET") or ""
        ).strip()
        if not consumer_key or not consumer_secret:
            raise FinderError(
                "Chuckbot's user OAuth consumer is not configured.",
                503,
                code="oauth_not_configured",
            )
        if not isinstance(access_token, dict):
            raise FinderError(
                "Sign out and authorize Chuckbot again before using this module.",
                401,
                code="oauth_required",
            )
        return cls(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_key=_token_part(access_token, "key"),
            access_secret=_token_part(access_token, "secret"),
        )

    def auth(self) -> OAuth1:
        """Create a fresh signer so concurrent REST calls never share nonce state."""
        return OAuth1(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.access_key,
            resource_owner_secret=self.access_secret,
        )


class WikiClient:
    """Small signed client for the selected wiki's authorization and TA APIs."""

    def __init__(
        self,
        wiki: WikiTarget,
        credentials: OAuthCredentials,
        *,
        transport=requests,
    ):
        """Bind a validated wiki, OAuth identity, and injectable HTTP transport."""
        self.wiki = wiki
        self.credentials = credentials
        self.transport = transport
        self.headers = {
            "User-Agent": os.environ.get(
                "TEMPORARY_ACCOUNT_FINDER_USER_AGENT",
                "Chuckbot-TemporaryAccountFinder/0.1 (https://buckbot.toolforge.org)",
            )
        }

    @staticmethod
    def _error_detail(response: Any) -> str:
        """Extract a bounded public MediaWiki error message when available."""
        try:
            payload = response.json()
        except Exception:
            return ""
        if not isinstance(payload, dict):
            return ""
        error = payload.get("error")
        candidates = [
            payload.get("message"),
            payload.get("detail"),
            error.get("info") if isinstance(error, dict) else None,
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()[:300]
        return ""

    def _post(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """POST one signed request and map remote failures to safe exceptions."""
        try:
            response = self.transport.post(
                url,
                auth=self.credentials.auth(),
                headers=self.headers,
                timeout=20,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise UpstreamError(f"Could not reach {self.wiki.host}.") from exc

        if response.status_code == 401:
            raise FinderError(
                "Your Wikimedia authorization has expired. Sign out and authorize Chuckbot again.",
                401,
                code="oauth_required",
            )
        if response.status_code == 403:
            detail = self._error_detail(response)
            message = "This account cannot reveal temporary-account data on the selected wiki."
            if detail:
                message = f"{message} {detail}"
            raise FinderError(message, 403, code="taiv_required")
        if response.status_code >= 400:
            detail = self._error_detail(response)
            message = f"{self.wiki.host} rejected the lookup"
            if detail:
                message += f": {detail}"
            raise UpstreamError(message + ".")

        try:
            payload = response.json()
        except Exception as exc:
            raise UpstreamError(
                f"{self.wiki.host} returned an invalid response."
            ) from exc
        if not isinstance(payload, dict):
            raise UpstreamError(f"{self.wiki.host} returned an invalid response.")
        if isinstance(payload.get("error"), dict):
            info = str(payload["error"].get("info") or "MediaWiki API error")[:300]
            raise UpstreamError(f"{self.wiki.host} rejected the request: {info}.")
        return payload

    def user_access(self) -> dict[str, Any]:
        """Return the OAuth actor and diagnose both user and consumer access."""
        payload = self._post(
            self.wiki.api_url,
            data={
                "action": "query",
                "meta": "userinfo",
                "uiprop": "rights|blockinfo",
                "format": "json",
                "formatversion": "2",
            },
        )
        userinfo = payload.get("query", {}).get("userinfo", {})
        if not isinstance(userinfo, dict) or userinfo.get("anon") is not None:
            raise FinderError(
                "Wikimedia did not recognize this OAuth session. Sign in again.",
                401,
                code="oauth_required",
            )
        rights = {str(right) for right in userinfo.get("rights", [])}
        reveal_rights = sorted(rights & REVEAL_RIGHTS)
        on_wiki_reveal_rights = reveal_rights
        # OAuth grants limit which of the user's rights an application may use.
        # Querying the public rights listing only when the effective OAuth view
        # lacks TAIV lets us distinguish a user permission problem from a
        # consumer that was registered without the corresponding grant.
        if not reveal_rights:
            on_wiki_reveal_rights = sorted(
                self.user_rights(str(userinfo.get("name") or "")) & REVEAL_RIGHTS
            )
        blocked = any(
            key in userinfo for key in ("blockid", "blockedby", "blockedbyid")
        )
        return {
            "username": str(userinfo.get("name") or ""),
            "eligible": bool(reveal_rights) and not blocked,
            "blocked": blocked,
            "reveal_rights": reveal_rights,
            "on_wiki_reveal_rights": on_wiki_reveal_rights,
            "oauth_grant_missing": bool(on_wiki_reveal_rights) and not reveal_rights,
        }

    def user_rights(self, username: str) -> set[str]:
        """Return one named user's public on-wiki rights without OAuth filtering."""
        payload = self._post(
            self.wiki.api_url,
            data={
                "action": "query",
                "list": "users",
                "ususers": username,
                "usprop": "rights",
                "format": "json",
                "formatversion": "2",
            },
        )
        users = payload.get("query", {}).get("users", [])
        if (
            not isinstance(users, list)
            or len(users) != 1
            or not isinstance(users[0], dict)
            or users[0].get("missing") is not None
            or not isinstance(users[0].get("rights"), list)
        ):
            raise UpstreamError(
                f"{self.wiki.host} returned an invalid user-rights response."
            )
        return {str(right) for right in users[0]["rights"]}

    def csrf_token(self) -> str:
        """Fetch the selected wiki's session-bound token for private REST calls."""
        payload = self._post(
            self.wiki.api_url,
            data={
                "action": "query",
                "meta": "tokens",
                "type": "csrf",
                "format": "json",
                "formatversion": "2",
            },
        )
        token = str(payload.get("query", {}).get("tokens", {}).get("csrftoken") or "")
        if not token or token == "+\\":
            raise FinderError(
                "Could not create an authenticated Wikimedia request. Sign in again.",
                401,
                code="oauth_required",
            )
        return token

    def connected_accounts(self, account: str, csrf_token: str) -> dict[str, Any]:
        """Ask CheckUser for one seed's authoritative connected-account set."""
        encoded_name = quote(account.replace(" ", "_"), safe="")
        payload = self._post(
            f"{self.wiki.rest_url}/checkuser/v0/connectedtemporaryaccounts/{encoded_name}",
            json={"token": csrf_token},
        )
        connected = payload.get("connectedAccounts")
        if not isinstance(connected, list) or not all(
            isinstance(name, str) for name in connected
        ):
            raise UpstreamError(
                f"{self.wiki.host} returned an invalid connected-account response."
            )
        try:
            ips_used_count = max(0, int(payload.get("ipsUsedCount", 0)))
        except (TypeError, ValueError) as exc:
            raise UpstreamError(
                f"{self.wiki.host} returned an invalid IP-count summary."
            ) from exc
        return {
            "seed": account,
            "connected_accounts": list(dict.fromkeys(connected)),
            "ips_used_count": ips_used_count,
        }

    def temporary_account_ips(self, account: str, csrf_token: str) -> list[str]:
        """Reveal one seed's current CheckUser IP set without persisting it."""
        encoded_name = quote(account.replace(" ", "_"), safe="")
        payload = self._post(
            f"{self.wiki.rest_url}/checkuser/v0/temporaryaccount/{encoded_name}",
            json={"token": csrf_token},
        )
        raw_ips = payload.get("ips")
        if not isinstance(raw_ips, list) or not all(
            isinstance(value, str) for value in raw_ips
        ):
            raise UpstreamError(
                f"{self.wiki.host} returned an invalid temporary-account IP response."
            )

        ips: list[str] = []
        seen: set[str] = set()
        for raw_ip in raw_ips:
            try:
                normalized = str(ipaddress.ip_address(raw_ip.strip()))
            except ValueError as exc:
                raise UpstreamError(
                    f"{self.wiki.host} returned an invalid IP address."
                ) from exc
            if normalized not in seen:
                seen.add(normalized)
                ips.append(normalized)
        return ips

    def investigate_account(
        self,
        account: str,
        csrf_token: str,
        *,
        include_ips: bool,
    ) -> dict[str, Any]:
        """Return connected names plus optional ephemeral IP evidence for one seed."""
        result = self.connected_accounts(account, csrf_token)
        if include_ips:
            result["ip_addresses"] = self.temporary_account_ips(account, csrf_token)
        return result


def _normalized_username(value: str) -> str:
    """Normalize MediaWiki username separators and case for identity comparison."""
    return " ".join(str(value or "").replace("_", " ").split()).casefold()


def _same_username(left: str, right: str) -> bool:
    """Compare the framework and OAuth actor using MediaWiki separator rules."""
    return _normalized_username(left) == _normalized_username(right)


def check_access(
    wiki_value: str,
    *,
    expected_username: str,
    access_token: dict[str, Any] | None,
    transport=requests,
) -> dict[str, Any]:
    """Return a live, selected-wiki TA reveal eligibility decision."""
    wiki = resolve_wiki(wiki_value)
    credentials = OAuthCredentials.from_session(access_token)
    client = WikiClient(wiki, credentials, transport=transport)
    access = client.user_access()
    if not _same_username(access["username"], expected_username):
        raise FinderError(
            "The Chuckbot session and Wikimedia OAuth user do not match. Sign in again.",
            401,
            code="oauth_mismatch",
        )
    return {"wiki": wiki.as_dict(), **access}


def find_connected_accounts(
    wiki_value: str,
    account_values: str | Iterable[Any],
    *,
    expected_username: str,
    access_token: dict[str, Any] | None,
    include_ips: bool = False,
    transport=requests,
) -> dict[str, Any]:
    """Find per-seed and combined connected temporary accounts on one wiki."""
    seeds = parse_seed_accounts(account_values)
    wiki = resolve_wiki(wiki_value)
    credentials = OAuthCredentials.from_session(access_token)
    client = WikiClient(wiki, credentials, transport=transport)

    access = client.user_access()
    if not _same_username(access["username"], expected_username):
        raise FinderError(
            "The Chuckbot session and Wikimedia OAuth user do not match. Sign in again.",
            401,
            code="oauth_mismatch",
        )
    if not access["eligible"]:
        reason = "This account does not have temporary-account IP reveal access on the selected wiki."
        code = "taiv_required"
        if access["blocked"]:
            reason = "Sitewide-blocked users cannot reveal temporary-account data on this wiki."
        elif access["oauth_grant_missing"]:
            reason = (
                "Your account has temporary-account reveal access on this wiki, "
                "but Chuckbot's current OAuth authorization does not include "
                "the checkuser-temporary-account grant. Add or approve the "
                "grant on the consumer if needed, then sign out and authorize "
                "Chuckbot again."
            )
            code = "oauth_grant_required"
        raise FinderError(reason, 403, code=code)

    csrf_token = client.csrf_token()
    results_by_seed: dict[str, dict[str, Any]] = {}
    errors_by_seed: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(seeds))) as executor:
        futures = {
            executor.submit(
                client.investigate_account,
                seed,
                csrf_token,
                include_ips=include_ips,
            ): seed
            for seed in seeds
        }
        for future in as_completed(futures):
            seed = futures[future]
            try:
                results_by_seed[seed] = future.result()
            except FinderError as exc:
                # Permission/auth changes are global to the selected wiki and
                # must never degrade into a misleading partial success.
                if exc.status_code in {401, 403}:
                    raise
                errors_by_seed[seed] = exc.detail
            except Exception:
                errors_by_seed[seed] = (
                    "The selected wiki could not complete this lookup."
                )

    ordered_results = [
        results_by_seed[seed] for seed in seeds if seed in results_by_seed
    ]
    ordered_errors = [
        {"seed": seed, "detail": errors_by_seed[seed]}
        for seed in seeds
        if seed in errors_by_seed
    ]
    combined: list[str] = []
    seen: set[str] = set()
    for result in ordered_results:
        for account in result["connected_accounts"]:
            key = account.casefold()
            if key not in seen:
                seen.add(key)
                combined.append(account)

    return {
        "wiki": wiki.as_dict(),
        "requested_by": access["username"],
        "seed_accounts": seeds,
        "results": ordered_results,
        "errors": ordered_errors,
        "combined_accounts": combined,
        "combined_count": len(combined),
        "complete": not ordered_errors,
        "privacy": {
            "contains_ip_addresses": bool(include_ips),
            "ip_storage": "none",
            "ip_retention_days": 0,
            "authorization_checked_by": ["chuckbot", wiki.host],
        },
    }
