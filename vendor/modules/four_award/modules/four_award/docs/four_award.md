# Chuck the 4awardhelper

Chuck the 4awardhelper reviews pending nominations on `Wikipedia:Four Award`.
It is designed to run as a Toolforge scheduled module job under Chuck the
Buckbot Framework.

## What It Does

- Reads the current Four Award nomination section.
- Verifies article creation, DYK, GA, and FA evidence.
- Produces a dry-run report with proposed edits and verification details.
- Optionally removes reviewed nominations, updates records, marks article
  history, and posts user-talk notices.

## Recommended Operating Mode

Keep `dry_run` enabled while testing new parser or verifier behavior. Use the
module run page to queue historical-diff tests against older versions of
`Wikipedia:Four Award`; historical tests intentionally skip duplicate-record
checks because current records would otherwise make old nominations fail.

## Important Settings

- `wiki_code`: MediaWiki language/site code, usually `en`.
- `wiki_family`: Pywikibot family, usually `wikipedia`.
- `wiki_api_url`: MediaWiki API endpoint for historical revision fetches.
- `four_page`: Nomination page, usually `Wikipedia:Four Award`.
- `records_page`: Records table page.
- `dry_run_report_page`: Optional userspace report page.
- `publish_dry_run_report`: Publish dry-run report to userspace when true.
- `allow_automated_approval`: Allow fully verified nominations to be processed
  without manual intervention.

## Module Rights

- `module:four_award:view_jobs`: View 4award runs and dry-run output.
- `module:four_award:run_jobs`: Queue historical dry-run tests and module jobs.
- `module:four_award:edit_config`: Edit non-secret module settings.
- `module:four_award:manage`: Manage the module.

Framework `view_all` also grants module job viewing.

## Frontend Ownership

The Vue app for this page lives in this module repository under
`modules/four_award/frontend`. Build it with:

```bash
npm install
npm run build
```

The build outputs packaged assets under `modules/four_award/static`, and the
module manifest points the framework at those assets with package-resource
references.
