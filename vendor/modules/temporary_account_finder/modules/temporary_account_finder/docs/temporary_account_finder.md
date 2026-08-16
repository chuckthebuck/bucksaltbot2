# Temporary Account Finder

Temporary Account Finder takes up to 50 temporary-account names and asks the
selected Wikimedia wiki for every active temporary account that CheckUser
considers connected to each seed. It shows both per-seed results and a deduplicated
combined list.

## Privacy and authorization

- Chuckbot uses the signed-in user's OAuth token. It does not use the bot's own
  identity for these lookups.
- Before searching, the backend checks the user's current effective rights on
  the selected wiki for `checkuser-temporary-account` or
  `checkuser-temporary-account-no-preference`.
- The wiki's CheckUser REST handler repeats the authorization check, rejects
  sitewide-blocked users, and records the access in the wiki's private access
  log.
- Chuckbot calls `/checkuser/v0/connectedtemporaryaccounts/{name}` for related
  names and, when the investigator asks to display IPs,
  `/checkuser/v0/temporaryaccount/{name}` for the current IP set.
- Revealed IPs exist only in the no-store HTTP response and the open browser
  page. Chuckbot does not write them to ToolsDB, Redis, logs, job payloads, or
  query history, so its current IP retention period is zero days.
- A future saved-query/history feature may retain query terms and related-account
  names indefinitely, but must strip IP fields before persistence. Any future IP
  cache must enforce deletion no later than 90 days after reveal.
- Results are limited to the selected wiki's current CheckUser retention window
  and to the endpoint's server-side result cap.

The OAuth consumer used by Chuckbot must include the
`checkuser-temporary-account` OAuth grant. After that grant is added, users may
need to sign out and authorize Chuckbot again. The user's own on-wiki right and,
where applicable, Temporary Account IP Reveal preference must also be active.

## Module access

The framework's `module:temporary_account_finder:view` grant controls whether the
UI appears in Chuckbot. Give that module grant only to intended investigators.
This discoverability grant is not trusted as TAIV authorization: every access
check and every search is separately checked against the selected wiki. The
framework's maintainer override also does not satisfy this wiki check. Maintainers
who need to use the module must hold TAIV (or another equivalent reveal right) on
the selected wiki themselves.

Common wiki values are `meta`, `commons`, and `enwiki`. Other public Wikimedia
project hostnames, such as `de.wikipedia.org` or `www.wikidata.org`, are also
accepted.
