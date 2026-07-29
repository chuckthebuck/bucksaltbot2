"""Saltlick: guided, forkable Pywikibot workflows."""

from .service import execute_workflow, run_saltlick
from .spec import WorkflowSpec

__all__ = ["WorkflowSpec", "execute_workflow", "run_saltlick"]
