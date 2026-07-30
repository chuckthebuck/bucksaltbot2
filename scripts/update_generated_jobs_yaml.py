"""Replace only the generated module-job block in a Toolforge jobs.yaml file."""

from __future__ import annotations

import argparse
from pathlib import Path


BEGIN_MARKER = "# BEGIN GENERATED MODULE JOBS"
END_MARKER = "# END GENERATED MODULE JOBS"


def replace_generated_block(jobs_text: str, generated_text: str) -> str:
    """Return jobs YAML with its one marked generated block replaced.

    The generator produces full YAML list entries. Static jobs, including the
    Celery worker and module controller, remain outside this block and are
    never changed by this helper.
    """
    if jobs_text.count(BEGIN_MARKER) != 1 or jobs_text.count(END_MARKER) != 1:
        raise ValueError("jobs.yaml must contain exactly one generated-jobs marker pair")
    start = jobs_text.index(BEGIN_MARKER)
    end = jobs_text.index(END_MARKER)
    if end < start:
        raise ValueError("generated-jobs end marker appears before its begin marker")

    before = jobs_text[: start + len(BEGIN_MARKER)]
    after = jobs_text[end:]
    body = generated_text.strip()
    return f"{before}\n{body}\n{after}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=Path, default=Path("jobs.yaml"))
    parser.add_argument("--generated", type=Path, required=True)
    args = parser.parse_args()

    updated = replace_generated_block(
        args.jobs.read_text(encoding="utf-8"),
        args.generated.read_text(encoding="utf-8"),
    )
    args.jobs.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
