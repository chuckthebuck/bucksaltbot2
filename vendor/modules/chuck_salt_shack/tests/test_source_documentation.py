"""Keep Chuck the Salt Shack's Python source documented as it grows."""

from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[1] / "modules" / "chuck_salt_shack"
)


def test_python_modules_classes_and_functions_have_docstrings():
    """Require comments at every Python module, class, and function boundary."""
    missing: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative_path = path.relative_to(PACKAGE_ROOT)
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

    assert not missing, "Undocumented Salt Shack source:\n" + "\n".join(missing)
