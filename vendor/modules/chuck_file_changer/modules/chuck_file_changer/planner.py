"""Validate text operations and build per-file preview/apply plans.

Planning is side-effect free: it transforms supplied wikitext, detects no-op
targets, and produces unified diffs.  The service decides whether a changed
plan item is only reported or passed to the wiki write adapter.
"""

from __future__ import annotations

import difflib
import re

from .models import FileChangeOperation, FileChangePlanItem, FileChangeTarget


# Operation modes are an explicit allowlist; payload values never select a
# Python function dynamically.
VALID_MODES = {"replace", "prepend", "append"}
_REGEX_LITERAL_RE = re.compile(r"^/(.*)/([a-z]*)$", re.S)


def operation_from_payload(payload: dict) -> FileChangeOperation:
    """Normalize one request operation and require its mode-specific text."""
    mode = str(payload.get("mode") or "replace").strip().lower()
    if mode not in VALID_MODES:
        raise ValueError("mode must be replace, prepend, or append")

    operation = FileChangeOperation(
        mode=mode,
        find=str(payload.get("find") or ""),
        replace=str(payload.get("replace") or ""),
        prepend=str(payload.get("prepend") or ""),
        append=str(payload.get("append") or ""),
        edit_summary=str(payload.get("edit_summary") or "").strip(),
        use_regex=_bool_value(payload.get("use_regex"), False),
    )

    if mode == "replace" and not operation.find:
        raise ValueError("replace mode requires find text")
    if mode == "prepend" and not operation.prepend:
        raise ValueError("prepend mode requires text")
    if mode == "append" and not operation.append:
        raise ValueError("append mode requires text")

    return operation


def _bool_value(value, default: bool) -> bool:
    """Coerce common form/config spellings without generic truthiness."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def _compile_pattern(pattern: str) -> re.Pattern:
    """Compile plain Python regex or VFC-style ``/pattern/ims`` syntax.

    Only the recognized case, multiline, and dot-all flags are applied. Python
    ``re.compile`` rejects malformed expressions before substitution; patterns
    are never evaluated as Python code.
    """
    flags = 0
    source = pattern
    literal = _REGEX_LITERAL_RE.match(pattern)
    if literal:
        source = literal.group(1)
        flag_text = literal.group(2)
        if "i" in flag_text:
            flags |= re.I
        if "m" in flag_text:
            flags |= re.M
        if "s" in flag_text:
            flags |= re.S
    return re.compile(source, flags)


def _python_replacement(text: str) -> str:
    """Translate VFC-style ``$1`` groups into Python replacement syntax."""
    return re.sub(r"\$(\d+)", r"\\\1", text)


def apply_operation(text: str, operation: FileChangeOperation) -> str:
    """Return transformed text without reading or writing a wiki page.

    Regex work uses Python's regular-expression engine, so costly patterns are
    still costly; previewing representative targets is the operational safety
    check before submitting the same operation for apply.
    """
    if operation.mode == "replace":
        if operation.use_regex:
            return _compile_pattern(operation.find).sub(
                _python_replacement(operation.replace),
                text,
            )
        # Literal replacement avoids regex interpretation unless the operator
        # explicitly selected the regex option.
        return text.replace(operation.find, operation.replace)
    if operation.mode == "prepend":
        prefix = operation.prepend
        # Insert one newline at the join only when neither empty-page nor
        # already-terminated prefix semantics provide it.
        separator = "" if prefix.endswith("\n") or not text else "\n"
        return f"{prefix}{separator}{text}"
    if operation.mode == "append":
        suffix = operation.append
        separator = "" if not text or text.endswith("\n") else "\n"
        return f"{text}{separator}{suffix}"
    raise ValueError("unsupported operation mode")


def make_diff(title: str, old_text: str, new_text: str) -> str:
    """Render the complete unified diff displayed and stored for one target."""
    return "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"{title} (before)",
            tofile=f"{title} (after)",
        )
    )


def plan_target(
    target: FileChangeTarget,
    operation: FileChangeOperation,
    page_text: str,
) -> FileChangePlanItem:
    """Classify a target as unchanged or changed and attach its diff."""
    new_text = apply_operation(page_text, operation)
    if new_text == page_text:
        return FileChangePlanItem(
            title=target.title,
            status="unchanged",
            old_text=page_text,
            new_text=new_text,
        )
    return FileChangePlanItem(
        title=target.title,
        status="changed",
        old_text=page_text,
        new_text=new_text,
        diff=make_diff(target.title, page_text, new_text),
    )


def default_summary(operation: FileChangeOperation) -> str:
    """Return an explicit operator summary or the mode-specific default."""
    if operation.edit_summary:
        return operation.edit_summary
    if operation.mode == "replace":
        return "Updating file page text with Chuck the File Changer"
    if operation.mode == "prepend":
        return "Adding file page text with Chuck the File Changer"
    return "Appending file page text with Chuck the File Changer"
