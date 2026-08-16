# Chuckbot Temporary Account Finder

A vendored Chuckbot module that accepts a list of Wikimedia temporary accounts
and finds the connected temporary accounts reported by CheckUser on a selected
wiki.

The module deliberately uses CheckUser's connected-accounts REST endpoint and
can optionally show CheckUser's current raw IP evidence in a no-store browser
response. It does not persist IP addresses. Every lookup is authorized and
logged by the selected wiki, using the signed-in user's OAuth credentials.

See `modules/temporary_account_finder/docs/temporary_account_finder.md` for
deployment and access-control details.
