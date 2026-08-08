# Rename the Framework and Create Its Deployment Repository

This framework is a starting point, not a hosted service. The checked example
is named `buckbot` and points at Chuck's repositories. Before a real deploy,
create **your own framework deployment repository** and choose a Toolforge tool
name. Then push the framework changes to that repository. Toolforge Build
Service builds exactly the repository URL and ref passed to `toolforge build
start`; it cannot see unpushed work, a different local clone, or changes made
only in an upstream module repository.

Keep the two repository roles separate:

| Repository | Contains | What a push changes |
| --- | --- | --- |
| Framework deployment repository | This framework, `jobs.yaml`, and vendored `vendor/modules/*` snapshots | The exact bundle Build Service deploys. This is the repo that must be cloned to `/data/project/<tool-name>`. |
| Module repository | A module's independently developed source package | Nothing in production until its reviewed contents are copied into the framework repository's `vendor/modules/<module>` snapshot and that framework commit is pushed. |

For example, if the new Toolforge tool is `my-bot`, use a framework deployment
repository such as `https://github.com/<owner>/my-bot-framework.git`. Its
Toolforge checkout is `/data/project/my-bot`, and the Build Service image is
`tool-my-bot/tool-my-bot:latest`. The module source repositories may be
elsewhere; they are not build inputs by themselves.

## 1. Create the framework deployment repository

Fork this repository in GitHub or create an empty repository and push a clone
of it. Use the new repository as `origin` in the working copy that you intend
to deploy:

```bash
git clone https://github.com/<owner>/my-bot-framework.git
cd my-bot-framework
git remote -v
git push -u origin main
```

If you began from an existing clone of this framework, confirm before pushing:

```bash
git remote set-url origin https://github.com/<owner>/my-bot-framework.git
git remote -v
git push -u origin main
```

Do not leave `origin` pointing at `chuckthebuck/bucksaltbot2` unless that is
intentionally the repository you want to deploy. The GitHub Actions workflow
runs only for the repository containing the workflow, so copy the deploy
secrets to the new framework deployment repository as well.

## 2. Replace deployment identity values

There are two types of names below. **Deployment identity** names must all
describe the same Toolforge tool. **Compatibility/code identifiers** can remain
as-is initially; rename them only as a deliberate code migration.

| Location | Replace `buckbot` with the new tool name? | Why |
| --- | --- | --- |
| `.github/workflows/toolforge-deploy.yml` | Yes: `become`, checkout path, and `REPO_DIR` | This workflow otherwise deploys the Buckbot account and checkout. |
| `project.toml` | Yes: `id` and `name` | Build project metadata should identify the new tool. |
| `service.manifest` | Yes: `buildservice-image` | Must be `tool-<tool-name>/tool-<tool-name>:latest`. |
| `jobs.yaml` | Yes: every `image:` and framework process `name:` | Jobs must use the new Build Service image and unique worker/controller names. Keep the generated-job markers intact. |
| Toolforge envvars | Yes: `BOT_NAME`, `TOOL_NAME`, `BUCKBOT_REDIS_NAMESPACE`, queue, and worker name | Gives the public hostname and isolates Redis/Celery work from Buckbot and other tools. |
| `scripts/toolforge-bootstrap.sh` invocation | Yes: pass `--tool-name <tool-name>` and `--repo-url <your-framework-repo>` | Creates matching Toolforge defaults and builds your repository. |
| GitHub repository secrets | Yes: add `TOOLFORGE_USERNAME` and `TOOLFORGE_DEPLOY_PRIVATE_KEY` to **your framework deployment repository** | The workflow runs from this repository, not from the original framework repo. |
| OAuth consumer settings | Yes | Register/allow the new callback URL: `https://<tool-name>.toolforge.org/mas-oauth-callback`, or set `USER_OAUTH_CALLBACK_URL`. |

`BUCKBOT_*`, `chuck_buckbot.modules`, and a few task names are compatibility
identifiers, not the Toolforge account name. They are safe to retain during a
first deployment. If you later rename them, change the same variable names and
Python entry-point group consistently across framework, modules, tests, and
automation; do not partially rename them. The `BUCKBOT_REDIS_NAMESPACE` value,
however, must be changed for every separate deployment even if its variable
name is retained.

Use this inventory while migrating:

```bash
rg -n -i 'buckbot|chuckbot|chuck_buckbot|bucksaltbot2|chuckthebuck' \
  --glob '!vendor/**' --glob '!.git/**'
```

Review each result rather than mass-replacing: docs and deployment identity
should change; historical compatibility paths and Python entry points may be
intentional.

## 3. Configure the deploy workflow and Toolforge checkout

Edit `.github/workflows/toolforge-deploy.yml` as one matched set, replacing:

```text
become buckbot
cd /data/project/buckbot
REPO_DIR=/data/project/buckbot
```

with the new Toolforge tool name and `/data/project/<tool-name>`. On Toolforge,
initialize that exact tool-home directory from **your framework deployment
repository**:

```bash
ssh login.toolforge.org
become <tool-name>
cd /data/project/<tool-name>
git init
git remote add origin https://github.com/<owner>/my-bot-framework.git
git fetch origin main
git checkout -B main origin/main
git remote -v
```

The directory is significant: the workflow's `cd`, the checkout's `origin`,
and `REPO_DIR` must all agree. A clone in a child directory or a checkout whose
origin still points to the original framework repository will be updated or
built incorrectly.

The deployment wrapper now defaults `REPO_URL` to the Toolforge checkout's
`origin`, which protects normal renamed deployments. For a manual recovery
deploy, set it explicitly if needed:

```bash
REPO_DIR=/data/project/<tool-name> \
REPO_URL=https://github.com/<owner>/my-bot-framework.git \
BRANCH=main BUILDPACK_CHANNEL=latest \
  bash scripts/toolforge-deploy-new-version.sh
```

## 4. Bootstrap and make future deploys effective

From the clean Toolforge checkout, first review and then apply:

```bash
bash scripts/toolforge-bootstrap.sh \
  --tool-name <tool-name> \
  --repo-url https://github.com/<owner>/my-bot-framework.git

bash scripts/toolforge-bootstrap.sh --apply --configure-env \
  --tool-name <tool-name> \
  --repo-url https://github.com/<owner>/my-bot-framework.git
```

After any framework or module change, the deploy sequence is:

1. For a module, commit its source repository, then refresh or copy its
   reviewed snapshot under `vendor/modules/` in the framework checkout.
2. Commit the resulting framework changes (including `jobs.yaml` when it
   changed) to the framework deployment repository.
3. Push that commit to the workflow's deployment branch, normally `main`.
4. The workflow updates `/data/project/<tool-name>` from that repository and
   asks Build Service to build that pushed revision.

The critical commit is step 2. A module-repository push alone is deliberately
not deployed because Toolforge builds the self-contained framework bundle and
does not clone modules during a build.
