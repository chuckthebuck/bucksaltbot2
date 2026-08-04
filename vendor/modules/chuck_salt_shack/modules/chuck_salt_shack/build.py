"""Compile or check the deterministic Saltlick image-audit registry."""

from __future__ import annotations

import argparse
from pathlib import Path

from .registry import (
    default_saltlicks_root,
    generated_registry_is_current,
    generated_registry_path,
    write_generated_registry,
)


def main(argv: list[str] | None = None) -> int:
    """Generate the audit artifact or fail CI when it differs from source.

    Runtime discovery does not read this file as mutable configuration; check
    mode exists to prove that reviewed source and the committed audit snapshot
    describe the same image.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=default_saltlicks_root(),
        help="Directory containing one subdirectory per Saltlick",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=generated_registry_path(),
        help="Generated registry YAML destination",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the generated registry is missing or stale",
    )
    args = parser.parse_args(argv)

    if args.check:
        if not generated_registry_is_current(args.output, root=args.root):
            parser.error(
                "generated Saltlick registry is stale; run "
                "python -m chuck_salt_shack.build"
            )
        print(f"Salt Shack registry is current: {args.output}")
        return 0

    output = write_generated_registry(args.output, root=args.root)
    print(f"Wrote Salt Shack registry: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
