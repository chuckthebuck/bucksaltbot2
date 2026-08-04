"""Keep hand-written production Python documented as the framework grows."""

from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# Tests describe behavior rather than production APIs; dependencies, runtime data,
# and generated assets are owned by their respective build tools.
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    ".venv-1",
    "__pycache__",
    "data",
    "generated",
    "node_modules",
    "static",
    "tests",
}


def _authored_python_paths() -> list[Path]:
    """Return deterministic paths for hand-written production Python sources."""
    return [
        path
        for path in sorted(REPOSITORY_ROOT.rglob("*.py"))
        if not EXCLUDED_DIRECTORY_NAMES.intersection(path.relative_to(REPOSITORY_ROOT).parts)
    ]


def test_authored_python_boundaries_have_docstrings() -> None:
    """Require a useful documentation boundary at each module, class, and function."""
    missing: list[str] = []

    for path in _authored_python_paths():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        relative_path = path.relative_to(REPOSITORY_ROOT)

        if ast.get_docstring(tree) is None:
            missing.append(f"{relative_path}: module")

        for node in ast.walk(tree):
            if not isinstance(
                node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue
            if ast.get_docstring(node) is None:
                missing.append(f"{relative_path}:{node.lineno} {node.name}")

    assert not missing, "Undocumented production source:\n" + "\n".join(missing)
