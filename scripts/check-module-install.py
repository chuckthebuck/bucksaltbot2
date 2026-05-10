#!/usr/bin/env python3
"""Print module install/entry-point diagnostics without touching ToolsDB."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

os.environ["ENABLE_MODULE_LOADING"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from router.module_registry import (  # noqa: E402
    discover_module_definitions,
    inspect_installed_module_entry_points,
    load_enabled_module_names,
)


def main() -> int:
    enabled = load_enabled_module_names()
    local_definitions = discover_module_definitions("modules")
    local_names = {definition.name for definition in local_definitions}
    entry_points = inspect_installed_module_entry_points()
    installed_names = {
        item["definition"]["name"]
        for item in entry_points
        if item.get("ok") and item.get("definition")
    }
    available_names = local_names | installed_names
    missing = sorted(enabled - available_names)
    failed_entry_points = [item for item in entry_points if not item.get("ok")]

    payload = {
        "enabled_modules": sorted(enabled),
        "local_manifest_modules": sorted(local_names),
        "installed_entry_points": entry_points,
        "available_modules": sorted(available_names),
        "missing_enabled_modules": missing,
        "failed_entry_points": failed_entry_points,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))

    if missing or failed_entry_points:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
