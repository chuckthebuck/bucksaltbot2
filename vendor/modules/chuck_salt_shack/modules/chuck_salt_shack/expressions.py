"""A deliberately small expression language for advanced text transforms.

Expressions look like Python, but are interpreted node-by-node. They cannot
import modules, access attributes, create comprehensions, or call arbitrary
objects. This keeps Saltlick useful without turning its shared UI into `exec`.
"""

from __future__ import annotations

import ast
import re
from typing import Any, Callable


MAX_EXPRESSION_LENGTH = 4000
MAX_RESULT_LENGTH = 2_000_000
_FLAG_VALUES = {
    "i": re.IGNORECASE,
    "m": re.MULTILINE,
    "s": re.DOTALL,
    "x": re.VERBOSE,
}


def _regex_flags(value: Any) -> int:
    """Translate the expression language's bounded regex flag set."""
    text = str(value or "").lower()
    invalid = sorted(set(text) - set(_FLAG_VALUES))
    if invalid:
        raise ValueError(f"unsupported regex flag(s): {''.join(invalid)}")
    flags = 0
    for flag in text:
        flags |= _FLAG_VALUES[flag]
    return flags


def _replace(text: Any, old: Any, new: Any, count: Any = -1) -> str:
    """Perform a literal replacement after predicting the result size."""
    source = str(text)
    needle = str(old)
    replacement = str(new)
    requested_count = int(count)
    if not needle:
        raise ValueError("replace() does not accept an empty find string")
    occurrences = source.count(needle)
    if requested_count >= 0:
        occurrences = min(occurrences, requested_count)
    predicted = len(source) + occurrences * (len(replacement) - len(needle))
    if predicted > MAX_RESULT_LENGTH:
        raise ValueError("replace() result is too large")
    return source.replace(needle, replacement, requested_count)


def _regex(
    pattern: Any,
    replacement: Any,
    text: Any,
    count: Any = 0,
    flags: Any = "",
) -> str:
    """Perform a regex replacement while enforcing the result-size limit."""
    source = str(text)
    replacement_text = str(replacement)
    requested_count = max(0, int(count))
    compiled = re.compile(str(pattern), _regex_flags(flags))
    predicted = len(source)
    matched = 0
    for match in compiled.finditer(source):
        predicted += len(match.expand(replacement_text)) - len(match.group(0))
        matched += 1
        if predicted > MAX_RESULT_LENGTH:
            raise ValueError("regex() result is too large")
        if requested_count and matched >= requested_count:
            break
    return compiled.sub(replacement_text, source, count=requested_count)


def _slice(value: Any, start: Any = None, stop: Any = None) -> Any:
    """Expose bounded Python-style slicing to the expression language."""
    start_value = None if start is None else int(start)
    stop_value = None if stop is None else int(stop)
    return value[start_value:stop_value]


_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "replace": _replace,
    "regex": _regex,
    "strip": lambda value: str(value).strip(),
    "lstrip": lambda value: str(value).lstrip(),
    "rstrip": lambda value: str(value).rstrip(),
    "lower": lambda value: str(value).lower(),
    "upper": lambda value: str(value).upper(),
    "titlecase": lambda value: str(value).title(),
    "contains": lambda value, needle: str(needle) in str(value),
    "starts_with": lambda value, prefix: str(value).startswith(str(prefix)),
    "ends_with": lambda value, suffix: str(value).endswith(str(suffix)),
    "length": lambda value: len(value),
    "slice": _slice,
}

_COMPARE_OPERATORS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: lambda left, right: left == right,
    ast.NotEq: lambda left, right: left != right,
    ast.Lt: lambda left, right: left < right,
    ast.LtE: lambda left, right: left <= right,
    ast.Gt: lambda left, right: left > right,
    ast.GtE: lambda left, right: left >= right,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}


def parse_expression(expression: str) -> ast.Expression:
    """Parse and structurally validate a Saltlick expression."""
    text = str(expression or "").strip()
    if not text:
        raise ValueError("expression transform requires an expression")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"expression exceeds {MAX_EXPRESSION_LENGTH} characters")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression: {exc.msg}") from exc
    if sum(1 for _node in ast.walk(tree)) > 200:
        raise ValueError("expression is too complex")
    _validate_node(tree.body)
    return tree


def _validate_node(node: ast.AST) -> None:
    """Reject syntax outside the expression language allowlist."""
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (str, int, float, bool, type(None))):
            raise ValueError("expression contains an unsupported constant")
        return
    if isinstance(node, ast.Name):
        if node.id not in {"text", "title", "namespace", "True", "False", "None"}:
            raise ValueError(f"unknown expression name: {node.id}")
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ValueError("expression calls an unsupported function")
        for argument in node.args:
            _validate_node(argument)
        for keyword in node.keywords:
            if keyword.arg is None:
                raise ValueError("expression does not support **kwargs")
            _validate_node(keyword.value)
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
        _validate_node(node.left)
        _validate_node(node.right)
        return
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        for value in node.values:
            _validate_node(value)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub)):
        _validate_node(node.operand)
        return
    if isinstance(node, ast.IfExp):
        _validate_node(node.test)
        _validate_node(node.body)
        _validate_node(node.orelse)
        return
    if isinstance(node, ast.Compare):
        _validate_node(node.left)
        for operator, comparator in zip(node.ops, node.comparators):
            if type(operator) not in _COMPARE_OPERATORS:
                raise ValueError("expression uses an unsupported comparison")
            _validate_node(comparator)
        return
    raise ValueError(f"expression node is not supported: {type(node).__name__}")


def evaluate_expression(
    expression: str,
    *,
    text: str,
    title: str,
    namespace: int,
) -> str:
    """Evaluate a validated expression and require a bounded string result."""
    tree = parse_expression(expression)
    result = _evaluate(
        tree.body,
        {"text": text, "title": title, "namespace": namespace},
    )
    if not isinstance(result, str):
        raise ValueError("expression result must be text")
    if len(result) > MAX_RESULT_LENGTH:
        raise ValueError(f"expression result exceeds {MAX_RESULT_LENGTH} characters")
    return result


def _evaluate(node: ast.AST, names: dict[str, Any]) -> Any:
    """Interpret one previously validated expression node."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return names[node.id]
    if isinstance(node, ast.Call):
        function = _FUNCTIONS[node.func.id]  # type: ignore[union-attr]
        args = [_evaluate(argument, names) for argument in node.args]
        kwargs = {
            keyword.arg: _evaluate(keyword.value, names)
            for keyword in node.keywords
            if keyword.arg is not None
        }
        result = function(*args, **kwargs)
        if hasattr(result, "__len__") and len(result) > MAX_RESULT_LENGTH:
            raise ValueError("expression result is too large")
        return result
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left, names)
        right = _evaluate(node.right, names)
        if isinstance(node.op, ast.Add):
            result = left + right
            if hasattr(result, "__len__") and len(result) > MAX_RESULT_LENGTH:
                raise ValueError("expression addition result is too large")
            return result
        if isinstance(node.op, ast.Mult):
            multiplier = right if isinstance(right, int) else left
            if isinstance(multiplier, int) and abs(multiplier) > MAX_RESULT_LENGTH:
                raise ValueError("expression multiplication is too large")
            sequence = left if isinstance(right, int) else right
            if (
                isinstance(multiplier, int)
                and hasattr(sequence, "__len__")
                and len(sequence) * abs(multiplier) > MAX_RESULT_LENGTH
            ):
                raise ValueError("expression multiplication result is too large")
            result = left * right
            if hasattr(result, "__len__") and len(result) > MAX_RESULT_LENGTH:
                raise ValueError("expression multiplication result is too large")
            return result
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for value in node.values:
                result = _evaluate(value, names)
                if not result:
                    return result
            return result
        result = False
        for value in node.values:
            result = _evaluate(value, names)
            if result:
                return result
        return result
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, names)
        return not value if isinstance(node.op, ast.Not) else -value
    if isinstance(node, ast.IfExp):
        branch = node.body if _evaluate(node.test, names) else node.orelse
        return _evaluate(branch, names)
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, names)
        for operator, comparator in zip(node.ops, node.comparators):
            right = _evaluate(comparator, names)
            if not _COMPARE_OPERATORS[type(operator)](left, right):
                return False
            left = right
        return True
    raise ValueError(f"expression node is not supported: {type(node).__name__}")
