#!/usr/bin/env bash
set -ex
cd 
git pull
dologmsg "./bucksaltbot2/scripts/toolforge-deploy-new-version.sh"
toolforge build start https://github.com/chuckthebuck/bucksaltbot2
toolforge webservice restart
toolforge jobs delete buckbot-celery
toolforge jobs load jobs.yaml
