"""Manifest entry point for Chuck the File Changer."""


def module_manifest():
    return {
        "name": "chuck_file_changer",
        "repo": "https://github.com/chuckthebuck/chuck-file-changer",
        "entry_point": "chuck_file_changer.service:run_file_change",
        "ui": True,
        "redis_namespace": "chuck_file_changer",
        "title": "Chuck the File Changer",
        "oauth_consumer_mode": "default",
        "rights": ["manage", "run_jobs", "edit_config", "apply_changes"],
        "frontend": {
            "script": "chuck_file_changer:static/chuck-file-changer-app.js",
            "styles": ["chuck_file_changer:static/style.css"],
            "props_id": "chuck-file-changer-props",
            "mount_id": "chuck-file-changer-app",
            "docs": "chuck_file_changer:docs/chuck_file_changer.md",
            "bundled": True,
        },
        "worker_jobs": [
            {
                "name": "file-change",
                "handler": "chuck_file_changer.service:run_file_change",
                "concurrency_policy": "forbid",
                "timeout_seconds": 900,
                "enabled": True,
            }
        ],
    }
