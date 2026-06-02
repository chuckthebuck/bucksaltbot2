#!/usr/bin/env python3
"""Validate a module manifest without bootstrapping the framework database."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys
import types


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_module_registry():
    root = Path(__file__).resolve().parent.parent
    router_dir = root / "router"
    sys.path.insert(0, str(root))

    router_pkg = types.ModuleType("router")
    router_pkg.__path__ = [str(router_dir)]  # type: ignore[attr-defined]
    sys.modules.setdefault("router", router_pkg)

    _load_module("router.module_schedule", router_dir / "module_schedule.py")
    return _load_module(
        "_buckbot_module_registry_standalone", router_dir / "module_registry.py"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="Path to module.toml or module.json")
    args = parser.parse_args()

    registry = _load_module_registry()
    definition = registry.load_module_definition(args.manifest)

    print(f"name={definition.name}")
    print(f"title={definition.title or definition.name}")
    print("rights=" + ",".join(definition.rights))
    if definition.worker_jobs:
        print("worker_jobs=" + ",".join(job.name for job in definition.worker_jobs))
    if definition.frontend:
        print(f"frontend.script={definition.frontend.script}")
        if definition.frontend.styles:
            print("frontend.styles=" + ",".join(definition.frontend.styles))
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
