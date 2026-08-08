"""Run a Saltlick recipe directly with Pywikibot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .service import execute_workflow
from .spec import WorkflowSpec


def _print_report(report: dict[str, Any]) -> None:
    """Render a compact terminal report without changing execution state."""
    for item in report.get("items") or []:
        status = str(item.get("status") or "unknown")
        title = str(item.get("title") or "")
        print(f"[{status}] {title}")
        if item.get("diff"):
            print(item["diff"])
        if item.get("error"):
            print(f"  error: {item['error']}")
    print(
        "Scanned {scanned_count}; changed {changed_count}; saved "
        "{saved_count}; errors {error_count}.".format(**report)
    )


def main(argv: list[str] | None = None) -> int:
    """Run a local recipe in preview mode unless live execution is confirmed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path, help="Saltlick recipe JSON")
    parser.add_argument(
        "--live",
        action="store_true",
        help="save edits; the default is a dry run",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm that a --live run may edit the wiki",
    )
    args = parser.parse_args(argv)
    if args.live and not args.yes:
        parser.error("--live requires --yes")

    workflow = WorkflowSpec.from_dict(
        json.loads(args.recipe.read_text(encoding="utf-8"))
    )
    import pywikibot

    site = pywikibot.Site(workflow.wiki.code, workflow.wiki.family)
    site.login()
    report = execute_workflow(site, workflow, dry_run=not args.live)
    _print_report(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
