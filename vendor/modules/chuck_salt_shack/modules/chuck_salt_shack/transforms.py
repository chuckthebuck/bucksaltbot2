"""Saltlick text transformation engine."""

from __future__ import annotations

import re

from .expressions import evaluate_expression
from .spec import TransformSpec


MAX_TRANSFORM_RESULT_LENGTH = 2_000_000
_FLAG_VALUES = {
    "i": re.IGNORECASE,
    "m": re.MULTILINE,
    "s": re.DOTALL,
    "x": re.VERBOSE,
}


def _flags(text: str) -> int:
    """Translate validated short regex flags into Python constants."""
    flags = 0
    for flag in text:
        flags |= _FLAG_VALUES[flag]
    return flags


def _tokens(value: str, *, old_text: str, title: str, namespace: int) -> str:
    """Expand the small template-token set with a size prediction."""
    predicted = len(value)
    replacements = {
        "{{text}}": old_text,
        "{{title}}": title,
        "{{namespace}}": str(namespace),
    }
    for token, replacement in replacements.items():
        predicted += value.count(token) * (len(replacement) - len(token))
    if predicted > MAX_TRANSFORM_RESULT_LENGTH:
        raise ValueError("template result is too large")
    return (
        value.replace("{{text}}", old_text)
        .replace("{{title}}", title)
        .replace("{{namespace}}", str(namespace))
    )


def _literal_replace(text: str, transform: TransformSpec) -> str:
    """Apply a literal replacement without exceeding the result bound."""
    occurrences = text.count(transform.find)
    if transform.count > 0:
        occurrences = min(occurrences, transform.count)
    predicted = len(text) + occurrences * (
        len(transform.replace) - len(transform.find)
    )
    if predicted > MAX_TRANSFORM_RESULT_LENGTH:
        raise ValueError("literal replacement result is too large")
    count = transform.count if transform.count > 0 else -1
    return text.replace(transform.find, transform.replace, count)


def _regex_replace(text: str, transform: TransformSpec) -> str:
    """Apply a regex replacement without exceeding the result bound."""
    compiled = re.compile(transform.pattern, _flags(transform.flags))
    predicted = len(text)
    matched = 0
    for match in compiled.finditer(text):
        predicted += len(match.expand(transform.replace)) - len(match.group(0))
        matched += 1
        if predicted > MAX_TRANSFORM_RESULT_LENGTH:
            raise ValueError("regex replacement result is too large")
        if transform.count and matched >= transform.count:
            break
    return compiled.sub(transform.replace, text, count=transform.count)


def apply_transform(
    text: str,
    transform: TransformSpec,
    *,
    title: str,
    namespace: int,
) -> str:
    """Apply one validated transformation."""
    if transform.type == "literal_replace":
        return _literal_replace(text, transform)
    if transform.type == "regex_replace":
        return _regex_replace(text, transform)
    if transform.type == "prepend":
        return f"{_tokens(transform.text, old_text=text, title=title, namespace=namespace)}{text}"
    if transform.type == "append":
        return f"{text}{_tokens(transform.text, old_text=text, title=title, namespace=namespace)}"
    if transform.type == "set_text":
        return _tokens(transform.text, old_text=text, title=title, namespace=namespace)
    if transform.type == "template":
        return _tokens(transform.text, old_text=text, title=title, namespace=namespace)
    if transform.type == "expression":
        return evaluate_expression(
            transform.expression,
            text=text,
            title=title,
            namespace=namespace,
        )
    raise ValueError(f"unsupported transform type: {transform.type}")


def apply_transforms(
    text: str,
    transforms: tuple[TransformSpec, ...],
    *,
    title: str,
    namespace: int,
) -> str:
    """Apply a workflow's transformation chain in order."""
    result = text
    for transform in transforms:
        result = apply_transform(
            result,
            transform,
            title=title,
            namespace=namespace,
        )
        if len(result) > MAX_TRANSFORM_RESULT_LENGTH:
            raise ValueError("transform chain result is too large")
    return result
