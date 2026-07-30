# First Toolforge Deployment

Use this guide once for a new Buckbot Toolforge tool account. The bootstrap
script performs the repeatable technical work; it deliberately does not create
the Toolforge account, grant database access, or choose OAuth credentials for
you.

## Before you begin

You need:

- A Toolforge tool account (for example, `buckbot`) that you can `become`.
- A public Git repository containing this framework.
- Wikimedia OAuth credentials for web login and bot edits.
- A clean checkout of the exact framework revision you want to deploy.

Toolforge automatically injects `TOOL_DATA_DIR`, `TOOL_REDIS_URI`, and the
ToolsDB credentials into buildservice web and job containers. Do not create or
override those `TOOL_*` values in the bootstrap script. Runtime configuration
and secrets are stored with Toolforge's envvars service, rather than in Git or
on NFS. [Toolforge environment-variable documentation](https://wikitech.wikimedia.org/wiki/Help:Toolforge/Envvars)

## Bootstrap

SSH to Toolforge, become the tool account, clone the repository, and inspect
the planned actions first:

```bash
ssh login.toolforge.org
become buckbot
git clone https://github.com/chuckthebuck/bucksaltbot2.git buckbot-framework
cd buckbot-framework
bash scripts/toolforge-bootstrap.sh --tool-name buckbot
```

The command above is a dry run. When it looks correct, run the first deploy:

```bash
bash scripts/toolforge-bootstrap.sh --apply --configure-env --tool-name buckbot
```

`--configure-env` sets the non-secret Buckbot defaults and has Toolforge prompt
for each secret without placing values in shell history. Use it only for the
first setup or an intentional secret rotation: Toolforge's `envvars create`
updates an existing variable.

The script then:

1. Builds the requested repository revision.
2. Runs the built image's `init-db` Procfile command as a one-off job.
3. Creates or upgrades all ToolsDB tables and registers enabled module
   manifests.
4. Generates module cron entries from that registered state.
5. Replaces only the marked generated block in `jobs.yaml`; framework-owned
   continuous jobs remain unchanged.
6. Starts the buildservice web process and loads `jobs.yaml`.

The generated file is written temporarily to
`$TOOL_DATA_DIR/buckbot-generated-jobs.yaml` so both the buildservice job and
the Toolforge shell can access it. It is useful for inspection and can be
removed after a successful deploy.

After a successful run, review and commit the updated `jobs.yaml` from the
Toolforge checkout before a later `git pull`:

```bash
git diff -- jobs.yaml
git add jobs.yaml
git commit -m "chore: refresh Toolforge jobs"
git push
```

This matters because module schedules are persisted in ToolsDB and then copied
into `jobs.yaml` for Toolforge. Leaving the file modified locally would block a
future fast-forward pull; restoring it without committing would make a later
deploy reload stale schedules.

## Required configuration

The bootstrap script prompts for these secrets:

- `SECRET_KEY`
- `USER_OAUTH_CONSUMER_KEY` and `USER_OAUTH_CONSUMER_SECRET`
- `CONSUMER_TOKEN`, `CONSUMER_SECRET`, `ACCESS_TOKEN`, and `ACCESS_SECRET`

It sets these non-secret runtime values using the tool name:

```text
BOT_NAME=buckbot
ENABLE_MODULE_LOADING=1
NOTDEV=1
BUCKBOT_REDIS_NAMESPACE=buckbot
BUCKBOT_CELERY_QUEUE=buckbot.celery
BUCKBOT_CELERY_WORKER_NAME=buckbot-celery
```

Choose a distinct tool name/Redis namespace for every staging tool or fork.
See [ENVIRONMENT.md](ENVIRONMENT.md) for the full map and shared-Redis rules.

## Verify the first deployment

```bash
toolforge build show
toolforge webservice buildservice logs -f
toolforge jobs list
toolforge jobs logs buckbot-celery -f
```

Open `https://buckbot.toolforge.org/`, log in, and confirm that `/modules`
lists the enabled modules. If the one-off schema job fails, inspect its logs:

```bash
toolforge jobs logs buckbot-bootstrap-init -f
```

## Later deploys

For normal updates, use `scripts/toolforge-deploy-new-version.sh` after review
and testing. Do not rerun `--configure-env` unless you intend to update
configuration or rotate secrets. If module cron definitions changed, use the
module-management UI to generate and review the updated `jobs.yaml`, commit it,
and load it before deployment.

## Safety notes

- The bootstrap refuses to run from a dirty checkout.
- Its default is dry run; build, database, webservice, and jobs changes require
  `--apply`.
- It never accepts secrets as arguments or reads them from a file.
- It updates only the block between `# BEGIN GENERATED MODULE JOBS` and
  `# END GENERATED MODULE JOBS` in `jobs.yaml`.
- A first deploy starts the webservice. For an already-running service, use the
  regular deploy script, which restarts it instead.
