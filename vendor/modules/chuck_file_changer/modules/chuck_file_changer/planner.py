from __future__ import annotations

import difflib

from .models import FileChangeOperation, FileChangePlanItem, FileChangeTarget


VALID_MODES = {"replace", "prepend", "append"}


def operation_from_payload(payload: dict) -> FileChangeOperation:
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
    )

    if mode == "replace" and not operation.find:
        raise ValueError("replace mode requires find text")
    if mode == "prepend" and not operation.prepend:
        raise ValueError("prepend mode requires text")
    if mode == "append" and not operation.append:
        raise ValueError("append mode requires text")

    return operation


def apply_operation(text: str, operation: FileChangeOperation) -> str:
    if operation.mode == "replace":
        return text.replace(operation.find, operation.replace)
    if operation.mode == "prepend":
        prefix = operation.prepend
        separator = "" if prefix.endswith("\n") or not text else "\n"
        return f"{prefix}{separator}{text}"
    if operation.mode == "append":
        suffix = operation.append
        separator = "" if not text or text.endswith("\n") else "\n"
        return f"{text}{separator}{suffix}"
    raise ValueError("unsupported operation mode")


def make_diff(title: str, old_text: str, new_text: str) -> str:
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
    if operation.edit_summary:
        return operation.edit_summary
    if operation.mode == "replace":
        return "Updating file page text with Chuck the File Changer"
    if operation.mode == "prepend":
        return "Adding file page text with Chuck the File Changer"
    return "Appending file page text with Chuck the File Changer"
