"""Make the src-layout package importable in module and framework test runs."""

from pathlib import Path
import sys


MODULES_DIRECTORY = Path(__file__).resolve().parents[1] / "modules"
sys.path.insert(0, str(MODULES_DIRECTORY))
