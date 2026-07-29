#!/usr/bin/env python3
"""Scaffold a framework-bundled Pywikibot module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO_URL = "https://github.com/chuckthebuck/bucksaltbot2"


def _validate_name(value: str) -> str:
    name = str(value or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", name):
        raise ValueError(
            "module name must be lowercase snake_case and start with a letter"
        )
    return name


def _manifest_text(
    name: str,
    *,
    title: str,
    repo_url: str,
    schedule: str | None,
) -> str:
    lines = [
        f"name = {json.dumps(name)}",
        f"title = {json.dumps(title)}",
        f"repo = {json.dumps(repo_url)}",
        f"entry_point = {json.dumps(f'modules.{name}.jobs:run')}",
        "ui = false",
        f"redis_namespace = {json.dumps(name)}",
        'rights = ["run_jobs"]',
        "",
    ]
    if schedule:
        lines.extend(
            [
                "[[jobs]]",
                'name = "run"',
                f"run = {json.dumps(schedule)}",
                f"handler = {json.dumps(f'modules.{name}.jobs:run')}",
                'execution_mode = "handler"',
                'concurrency_policy = "forbid"',
                "timeout_seconds = 300",
                "enabled = true",
            ]
        )
    else:
        lines.extend(
            [
                "[[worker_jobs]]",
                'name = "run"',
                f"handler = {json.dumps(f'modules.{name}.jobs:run')}",
                'concurrency_policy = "forbid"',
                "timeout_seconds = 300",
                "enabled = true",
            ]
        )
    return "\n".join(lines) + "\n"


def _jobs_text(name: str) -> str:
    return f'''"""Framework-managed Pywikibot job for {name}."""

from __future__ import annotations


def run(ctx, payload):
    """Run the module's reviewed Pywikibot workflow."""
    ctx.check_cancelled()
    ctx.logger.log(f"Starting {{ctx.module_name}}/{{ctx.job_name}}")

    # Uncomment when the workflow needs a logged-in site:
    # site = ctx.site(
    #     str(payload.get("code") or "commons"),
    #     str(payload.get("family") or "commons"),
    # )
    # import pywikibot
    # page = pywikibot.Page(site, "File:Example.jpg")

    return {{
        "ok": True,
        "dry_run": bool(ctx.config.get("dry_run", True)),
        "payload": payload,
    }}
'''


def _enable_module(enabled_file: Path, name: str) -> None:
    existing = enabled_file.read_text(encoding="utf-8") if enabled_file.exists() else ""
    enabled_names = {
        line.split("#", 1)[0].strip()
        for line in existing.splitlines()
        if line.split("#", 1)[0].strip()
    }
    if name in enabled_names:
        return
    separator = "" if not existing or existing.endswith("\n") else "\n"
    enabled_file.write_text(
        f"{existing}{separator}{name}\n",
        encoding="utf-8",
    )


def scaffold_module(
    root: Path,
    name: str,
    *,
    title: str | None = None,
    repo_url: str = DEFAULT_REPO_URL,
    schedule: str | None = None,
    enable: bool = False,
) -> Path:
    """Create a new bundled module and return its directory."""
    name = _validate_name(name)
    module_dir = root / "modules" / name
    if module_dir.exists():
        raise FileExistsError(f"module directory already exists: {module_dir}")

    module_dir.mkdir(parents=True)
    (module_dir / "__init__.py").write_text(
        f'"""Framework-bundled {name} module."""\n',
        encoding="utf-8",
    )
    (module_dir / "jobs.py").write_text(_jobs_text(name), encoding="utf-8")
    (module_dir / "module.toml").write_text(
        _manifest_text(
            name,
            title=str(title or name.replace("_", " ").title()),
            repo_url=str(repo_url or DEFAULT_REPO_URL),
            schedule=str(schedule).strip() if schedule else None,
        ),
        encoding="utf-8",
    )

    if enable:
        _enable_module(root / "enabled-modules.txt", name)
    return module_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="lowercase snake_case module name")
    parser.add_argument("--title", help="human-readable module title")
    parser.add_argument("--repo", default=DEFAULT_REPO_URL, help="source repository URL")
    parser.add_argument(
        "--schedule",
        help="create a cron handler, e.g. 'every hour'; default is a manual worker job",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="also append the module to enabled-modules.txt",
    )
    args = parser.parse_args(argv)

    try:
        module_dir = scaffold_module(
            REPO_ROOT,
            args.name,
            title=args.title,
            repo_url=args.repo,
            schedule=args.schedule,
            enable=args.enable,
        )
    except (FileExistsError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Created {module_dir}")
    print(f"Edit {module_dir / 'jobs.py'} with the custom Pywikibot workflow.")
    print(
        "Validate with: python scripts/check-module-manifest.py "
        f"{module_dir / 'module.toml'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
