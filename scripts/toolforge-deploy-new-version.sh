#!/usr/bin/env bash
set -ex
cd matchandsplit
git pull
dologmsg "./matchandsplit/scripts/toolforge-deploy-new-version.sh"
toolforge build start https://gitlab.wikimedia.org/toolforge-repos/matchandsplit.git
toolforge webservice restart
toolforge jobs delete mascelery
toolforge jobs load jobs.yaml