"""Chuck the 4awardhelper module manifest."""


def module_manifest():
    return {
        "name": "four_award",
        "repo": "https://github.com/chuckthebuck/module4awardhelper",
        "entry_point": "chuck_the_4awardhelper.service:run_four_award_sync",
        "ui": True,
        "redis_namespace": "four_award",
        "title": "Chuck the 4awardhelper",
        "oauth_consumer_mode": "default",
        "rights": ["manage", "run_jobs", "edit_config"],
        "frontend": {
            "script": "chuck_the_4awardhelper:static/four-award-app.js",
            "styles": ["chuck_the_4awardhelper:static/style.css"],
            "props_id": "four-award-props",
            "mount_id": "four-award-app",
            "docs": "chuck_the_4awardhelper:docs/four_award.md",
            "bundled": True,
        },
        "jobs": [
            {
                "name": "four-award-sync",
                "run": "Daily at 00:00",
                "handler": "chuck_the_4awardhelper.service:run_four_award_sync",
                "execution_mode": "k8s_job",
                "concurrency_policy": "forbid",
                "timeout_seconds": 600,
                "enabled": True,
            }
        ],
    }
