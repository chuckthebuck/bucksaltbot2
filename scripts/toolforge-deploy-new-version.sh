#!/usr/bin/env bash
set -ex
cd 
git pull
toolforge build start https://github.com/chuckthebuck/bucksaltbot2
toolforge jobs delete buckbot-celery
toolforge jobs delete buckbot-ping
toolforge webservice restart
toolforge jobs load jobs.yaml
toolforge jobs list
