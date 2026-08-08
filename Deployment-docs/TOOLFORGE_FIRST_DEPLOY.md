# First Toolforge Deployment

Use this guide once for a new Toolforge tool account. The bootstrap script
creates the deploy services and schema; it does not create the tool account,
OAuth consumers, GitHub credentials, or a repository checkout.

The checked GitHub deploy workflow is an example for `buckbot`. If you are
adopting the framework, first follow
[RENAMING_AND_REPOSITORIES.md](RENAMING_AND_REPOSITORIES.md): create and push
your framework deployment repository, then change the workflow target,
checkout path, namespace, and repository secrets. Build Service can build only
the repository you name; it does not infer your fork from a local checkout.

## Prerequisites

You need permission to `become` the Toolforge tool account, a public framework
repository and reviewed revision, OAuth credentials for login and bot edits,
and a clean checkout at the exact path used by the later deploy workflow.

Toolforge secrets belong in `toolforge envvars`, not Git or shell history.
Existing Toolforge `replica.my.cnf` credentials are supported and ignored by
Git.

## Create the workflow checkout

For the checked production workflow, the repository root must itself be
`/data/project/<tool-name>`; cloning into a child directory creates a checkout
the workflow will never update. Replace every placeholder below with your own
tool and framework deployment repository. The `buckbot` values are only the
checked example.

On a new tool account, initialize the existing tool home as the checkout:

```bash
ssh login.toolforge.org
become <tool-name>
cd /data/project/<tool-name>
git init
git remote add origin https://github.com/<owner>/<framework-deployment-repo>.git
git fetch origin main
git checkout -B main origin/main
git status --short
```

If a checkout or `origin` already exists, inspect and repair that specific
configuration instead of repeating initialization. The bootstrap refuses a
dirty checkout.

## Review and apply bootstrap

The first command is a dry run:

```bash
bash scripts/toolforge-bootstrap.sh --tool-name <tool-name> \
  --repo-url https://github.com/<owner>/<framework-deployment-repo>.git
```

After reviewing its exact operations:

```bash
bash scripts/toolforge-bootstrap.sh --apply --configure-env --tool-name <tool-name> \
  --repo-url https://github.com/<owner>/<framework-deployment-repo>.git
```

`--configure-env` creates non-secret defaults and asks Toolforge to prompt for
each secret without echoing it. Use it only for initial setup or intentional
rotation.

The applied bootstrap starts a Build Service build, runs the built image's
`init-db` command, creates/upgrades tables and registers enabled manifests,
generates module schedules, replaces only the marked block in `jobs.yaml`,
starts the webservice, and loads all checked jobs.

The generated-only YAML is also written to
`$TOOL_DATA_DIR/<tool-name>-generated-jobs.yaml` for review. Repository
`jobs.yaml` remains the deployment authority.

## Configuration created by bootstrap

The script prompts for `SECRET_KEY`, both `USER_OAUTH_*` values, and the four
Pywikibot `CONSUMER_*`/`ACCESS_*` values. For production it creates:

```text
BOT_NAME=<tool-name>
ENABLE_MODULE_LOADING=1
NOTDEV=1
BUCKBOT_REDIS_NAMESPACE=<tool-name>
BUCKBOT_CELERY_QUEUE=<tool-name>.celery
BUCKBOT_CELERY_WORKER_NAME=<tool-name>-celery
```

See [ENVIRONMENT.md](ENVIRONMENT.md) for database precedence and Redis
isolation.

## Preserve generated schedules

After bootstrap, inspect:

```bash
git diff -- jobs.yaml
toolforge jobs list
```

If `jobs.yaml` changed, commit and push it from a GitHub-authenticated checkout.
If the Toolforge checkout cannot push, copy the diff to a trusted developer
checkout, commit/push it there, then make Toolforge match that remote commit
before automated deploys. Do not leave an uncommitted `jobs.yaml`: the normal
wrapper fast-forwards the checkout and reloads the checked file.

## Verify and enable normal deployment

Open `https://<tool-name>.toolforge.org/`, complete OAuth login, and verify
`/modules`, module UIs, Rollback worker health, and `toolforge jobs list`.
The bootstrap init job is named `<tool-name>-bootstrap-init` for log lookup.

Configure GitHub secrets `TOOLFORGE_USERNAME` and
`TOOLFORGE_DEPLOY_PRIVATE_KEY` as described in the root README. Pushes to
`main` then run `.github/workflows/toolforge-deploy.yml`.

Routine deployments invoke `scripts/toolforge-deploy-new-version.sh`: update
checkout, build, restart web, flush jobs, and load committed `jobs.yaml`. It
does not rerun `init-db` or regenerate schedules. Bootstrap is for first setup,
not normal releases.

## Bootstrap safety properties

- Dry run is the default; state changes require `--apply`.
- A dirty checkout is rejected.
- Secrets are never command-line arguments or project-file inputs.
- Only the generated jobs marker block is rewritten.
- First deploy starts the webservice; routine deploys restart it.
