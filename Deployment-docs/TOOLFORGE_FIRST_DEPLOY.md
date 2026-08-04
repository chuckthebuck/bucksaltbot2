# First Toolforge Deployment

Use this guide once for a new Buckbot Toolforge tool account. The bootstrap
script creates the deploy services and schema; it does not create the tool
account, OAuth consumers, GitHub credentials, or a repository checkout.

The checked GitHub deploy workflow targets the `buckbot` tool and hardcodes the
checkout `/data/project/buckbot`. A staging tool or fork must deliberately
change the workflow target, checkout path, namespace, and repository secrets.

## Prerequisites

You need permission to `become` the Toolforge tool account, a public framework
repository and reviewed revision, OAuth credentials for login and bot edits,
and a clean checkout at the exact path used by the later deploy workflow.

Toolforge secrets belong in `toolforge envvars`, not Git or shell history.
Existing Toolforge `replica.my.cnf` credentials are supported and ignored by
Git.

## Create the workflow checkout

For the checked production workflow, the repository root must itself be
`/data/project/buckbot`; cloning into a `buckbot-framework` child creates a
checkout the workflow will never update.

On a new tool account, initialize the existing tool home as the checkout:

```bash
ssh login.toolforge.org
become buckbot
cd /data/project/buckbot
git init
git remote add origin https://github.com/chuckthebuck/bucksaltbot2.git
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
bash scripts/toolforge-bootstrap.sh --tool-name buckbot
```

After reviewing its exact operations:

```bash
bash scripts/toolforge-bootstrap.sh --apply --configure-env --tool-name buckbot
```

`--configure-env` creates non-secret defaults and asks Toolforge to prompt for
each secret without echoing it. Use it only for initial setup or intentional
rotation.

The applied bootstrap starts a Build Service build, runs the built image's
`init-db` command, creates/upgrades tables and registers enabled manifests,
generates module schedules, replaces only the marked block in `jobs.yaml`,
starts the webservice, and loads all checked jobs.

The generated-only YAML is also written to
`$TOOL_DATA_DIR/buckbot-generated-jobs.yaml` for review. Repository
`jobs.yaml` remains the deployment authority.

## Configuration created by bootstrap

The script prompts for `SECRET_KEY`, both `USER_OAUTH_*` values, and the four
Pywikibot `CONSUMER_*`/`ACCESS_*` values. For production it creates:

```text
BOT_NAME=buckbot
ENABLE_MODULE_LOADING=1
NOTDEV=1
BUCKBOT_REDIS_NAMESPACE=buckbot
BUCKBOT_CELERY_QUEUE=buckbot.celery
BUCKBOT_CELERY_WORKER_NAME=buckbot-celery
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

Open `https://buckbot.toolforge.org/`, complete OAuth login, and verify
`/modules`, module UIs, Rollback worker health, and `toolforge jobs list`.
The default bootstrap init job is named `buckbot-bootstrap-init` for log lookup.

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
