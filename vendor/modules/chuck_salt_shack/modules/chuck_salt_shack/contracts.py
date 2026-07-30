"""Salt Shack's versioned Saltlick input, output, and action contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import json
import re
from typing import Any


CONTRACT_VERSION = 1
MAX_ARGUMENTS = 100
MAX_PAGE_VALUES = 500
MAX_TEXT_LENGTH = 100_000
INPUT_TYPES = {
    "string",
    "text",
    "integer",
    "number",
    "boolean",
    "choice",
    "wiki",
    "namespace",
    "page",
    "pages",
    "user",
    "date",
    "datetime",
}
OUTPUT_TYPES = {
    "string",
    "number",
    "boolean",
    "message",
    "page",
    "pages",
    "table",
    "json",
}
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{1,63}")
_ACTION_TYPE = re.compile(r"[a-z][a-z0-9_.-]{2,127}")


def _mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    """Require and copy a mapping so callers cannot mutate contract input."""
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return dict(value)


def _label_from_name(name: str) -> str:
    """Turn a stable identifier into a human-readable default label."""
    return name.replace("_", " ").replace("-", " ").strip().title()


def _identifier(value: Any, *, field_name: str) -> str:
    """Normalize and validate an API-safe lowercase identifier."""
    text = str(value or "").strip().lower().replace("-", "_")
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(
            f"{field_name} must start with a letter and contain lowercase "
            "letters, numbers, or underscores"
        )
    return text


def _bounded_text(
    value: Any,
    *,
    field_name: str,
    required: bool = False,
    limit: int = MAX_TEXT_LENGTH,
) -> str:
    """Normalize user text while enforcing required and length constraints."""
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field_name} is required")
    if len(text) > limit:
        raise ValueError(f"{field_name} exceeds {limit} characters")
    return text


def _number(
    value: Any,
    *,
    field_name: str,
    integer: bool,
    minimum: float | None = None,
    maximum: float | None = None,
) -> int | float:
    """Coerce a bounded numeric field with integer-aware validation."""
    try:
        parsed: int | float = int(value) if integer else float(value)
    except (TypeError, ValueError) as exc:
        kind = "an integer" if integer else "a number"
        raise ValueError(f"{field_name} must be {kind}") from exc
    if isinstance(value, float) and integer and not value.is_integer():
        raise ValueError(f"{field_name} must be an integer")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field_name} must be at least {minimum:g}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{field_name} must be at most {maximum:g}")
    return parsed


def _normalize_namespace_policy(raw: Any, *, field_name: str) -> dict[str, Any]:
    """Normalize fixed or selectable namespace rules for page inputs."""
    data = {} if raw in (None, "") else _mapping(raw, field_name=field_name)
    selectable = bool(data.get("selectable", False))
    allowed_raw = data.get("allowed", [])
    if allowed_raw in (None, ""):
        allowed_raw = []
    if not isinstance(allowed_raw, list):
        raise ValueError(f"{field_name}.allowed must be a list")
    allowed: list[int] = []
    for value in allowed_raw:
        namespace = int(
            _number(
                value,
                field_name=f"{field_name}.allowed",
                integer=True,
                minimum=-2,
                maximum=5000,
            )
        )
        if namespace not in allowed:
            allowed.append(namespace)
    default_raw = data.get("default")
    default = None
    if default_raw is not None:
        default = int(
            _number(
                default_raw,
                field_name=f"{field_name}.default",
                integer=True,
                minimum=-2,
                maximum=5000,
            )
        )
    if default is not None and allowed and default not in allowed:
        raise ValueError(f"{field_name}.default must be in {field_name}.allowed")
    if not selectable and default is None and len(allowed) == 1:
        default = allowed[0]
    return {
        "selectable": selectable,
        "allowed": allowed,
        "default": default,
    }


def _normalize_choices(raw: Any, *, field_name: str) -> list[dict[str, Any]]:
    """Normalize labeled choice values and reject duplicate options."""
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{field_name} must be a non-empty list")
    choices: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if isinstance(item, dict):
            value = item.get("value")
            label = str(item.get("label") or value or "").strip()
        else:
            value = item
            label = str(item).strip()
        key = json.dumps(value, sort_keys=True, default=str)
        if value is None or not label:
            raise ValueError(f"{field_name}[{index}] requires value and label")
        if key in seen:
            raise ValueError(f"{field_name} contains a duplicate value")
        seen.add(key)
        choices.append({"value": value, "label": label})
    return choices


def normalize_contract(raw: Any, *, saltlick_id: str) -> dict[str, Any]:
    """Return one canonical contract suitable for code generation and APIs."""
    data = _mapping(raw, field_name=f"{saltlick_id} contract")
    version = int(data.get("contract", data.get("version", CONTRACT_VERSION)))
    if version != CONTRACT_VERSION:
        raise ValueError(
            f"{saltlick_id} uses unsupported contract version {version}; "
            f"expected {CONTRACT_VERSION}"
        )
    normalized_id = _identifier(saltlick_id, field_name="Saltlick directory name")
    display_name = _bounded_text(
        data.get("display_name") or _label_from_name(normalized_id),
        field_name=f"{normalized_id}.display_name",
        required=True,
        limit=100,
    )
    description = _bounded_text(
        data.get("description"),
        field_name=f"{normalized_id}.description",
        limit=1000,
    )
    entrypoint = _bounded_text(
        data.get("entrypoint") or "script.py:run",
        field_name=f"{normalized_id}.entrypoint",
        required=True,
        limit=200,
    )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.py:[A-Za-z_][A-Za-z0-9_]*", entrypoint):
        raise ValueError(
            f"{normalized_id}.entrypoint must look like script.py:run"
        )

    raw_inputs = data.get("inputs", {})
    if raw_inputs in (None, ""):
        raw_inputs = {}
    inputs_data = _mapping(raw_inputs, field_name=f"{normalized_id}.inputs")
    inputs: dict[str, dict[str, Any]] = {}
    for raw_name, raw_spec in inputs_data.items():
        name = _identifier(raw_name, field_name=f"{normalized_id} input name")
        spec = _mapping(raw_spec, field_name=f"{normalized_id}.inputs.{name}")
        input_type = str(spec.get("type") or "string").strip().lower()
        if input_type not in INPUT_TYPES:
            raise ValueError(
                f"{normalized_id}.inputs.{name} has unsupported type {input_type}"
            )
        normalized: dict[str, Any] = {
            "type": input_type,
            "label": _bounded_text(
                spec.get("label") or _label_from_name(name),
                field_name=f"{normalized_id}.inputs.{name}.label",
                required=True,
                limit=100,
            ),
            "description": _bounded_text(
                spec.get("description"),
                field_name=f"{normalized_id}.inputs.{name}.description",
                limit=500,
            ),
            "required": bool(spec.get("required", False)),
        }
        if "default" in spec:
            normalized["default"] = deepcopy(spec["default"])
        if input_type == "choice":
            normalized["choices"] = _normalize_choices(
                spec.get("choices"),
                field_name=f"{normalized_id}.inputs.{name}.choices",
            )
        if input_type in {"integer", "number"}:
            if spec.get("minimum") is not None:
                normalized["minimum"] = float(spec["minimum"])
            if spec.get("maximum") is not None:
                normalized["maximum"] = float(spec["maximum"])
            if (
                normalized.get("minimum") is not None
                and normalized.get("maximum") is not None
                and normalized["minimum"] > normalized["maximum"]
            ):
                raise ValueError(
                    f"{normalized_id}.inputs.{name} minimum exceeds maximum"
                )
        if input_type in {"page", "pages"}:
            normalized["namespace"] = _normalize_namespace_policy(
                spec.get("namespace"),
                field_name=f"{normalized_id}.inputs.{name}.namespace",
            )
        if input_type in {"namespace", "page", "pages"} and spec.get(
            "wiki_input"
        ) is not None:
            normalized["wiki_input"] = _identifier(
                spec["wiki_input"],
                field_name=f"{normalized_id}.inputs.{name}.wiki_input",
            )
        if input_type == "pages":
            max_items = spec.get("max_items", MAX_PAGE_VALUES)
            normalized["max_items"] = int(
                _number(
                    max_items,
                    field_name=f"{normalized_id}.inputs.{name}.max_items",
                    integer=True,
                    minimum=1,
                    maximum=MAX_PAGE_VALUES,
                )
            )
        inputs[name] = normalized

    wiki_inputs = [
        name for name, spec in inputs.items() if spec["type"] == "wiki"
    ]
    for name, spec in inputs.items():
        if spec["type"] not in {"namespace", "page", "pages"}:
            continue
        wiki_input = spec.get("wiki_input")
        if wiki_input is None and len(wiki_inputs) == 1:
            spec["wiki_input"] = wiki_inputs[0]
            continue
        if wiki_input is not None and (
            wiki_input not in inputs or inputs[wiki_input]["type"] != "wiki"
        ):
            raise ValueError(
                f"{normalized_id}.inputs.{name}.wiki_input must name a wiki input"
            )

    outputs_data = data.get("outputs", {})
    if outputs_data in (None, ""):
        outputs_data = {}
    outputs_raw = _mapping(outputs_data, field_name=f"{normalized_id}.outputs")
    outputs: dict[str, dict[str, Any]] = {}
    for raw_name, raw_spec in outputs_raw.items():
        name = _identifier(raw_name, field_name=f"{normalized_id} output name")
        spec = _mapping(raw_spec, field_name=f"{normalized_id}.outputs.{name}")
        output_type = str(spec.get("type") or "json").strip().lower()
        if output_type not in OUTPUT_TYPES:
            raise ValueError(
                f"{normalized_id}.outputs.{name} has unsupported type {output_type}"
            )
        normalized_output: dict[str, Any] = {
            "type": output_type,
            "label": _bounded_text(
                spec.get("label") or _label_from_name(name),
                field_name=f"{normalized_id}.outputs.{name}.label",
                required=True,
                limit=100,
            ),
            "description": _bounded_text(
                spec.get("description"),
                field_name=f"{normalized_id}.outputs.{name}.description",
                limit=500,
            ),
            "optional": bool(spec.get("optional", False)),
        }
        if output_type == "table":
            columns_raw = _mapping(
                spec.get("columns"),
                field_name=f"{normalized_id}.outputs.{name}.columns",
            )
            if not columns_raw:
                raise ValueError(
                    f"{normalized_id}.outputs.{name}.columns cannot be empty"
                )
            columns: dict[str, dict[str, Any]] = {}
            for raw_column, raw_column_spec in columns_raw.items():
                column = _identifier(
                    raw_column,
                    field_name=f"{normalized_id}.outputs.{name} column",
                )
                column_spec = _mapping(
                    raw_column_spec,
                    field_name=(
                        f"{normalized_id}.outputs.{name}.columns.{column}"
                    ),
                )
                column_type = str(
                    column_spec.get("type") or "string"
                ).strip().lower()
                if column_type not in OUTPUT_TYPES - {"table"}:
                    raise ValueError(
                        f"{normalized_id}.outputs.{name}.columns.{column} "
                        f"has unsupported type {column_type}"
                    )
                columns[column] = {
                    "type": column_type,
                    "label": _bounded_text(
                        column_spec.get("label") or _label_from_name(column),
                        field_name=(
                            f"{normalized_id}.outputs.{name}.columns."
                            f"{column}.label"
                        ),
                        required=True,
                        limit=100,
                    ),
                    "optional": bool(column_spec.get("optional", False)),
                }
            normalized_output["columns"] = columns
        outputs[name] = normalized_output

    actions_data = data.get("actions", {})
    if actions_data in (None, ""):
        actions_data = {}
    actions_raw = _mapping(actions_data, field_name=f"{normalized_id}.actions")
    allowed_raw = actions_raw.get("allowed", [])
    if allowed_raw in (None, ""):
        allowed_raw = []
    if not isinstance(allowed_raw, list):
        raise ValueError(f"{normalized_id}.actions.allowed must be a list")
    allowed: list[str] = []
    for value in allowed_raw:
        action_type = str(value or "").strip()
        if not _ACTION_TYPE.fullmatch(action_type):
            raise ValueError(
                f"{normalized_id}.actions.allowed contains invalid action type"
            )
        if action_type not in allowed:
            allowed.append(action_type)

    return {
        "contract": CONTRACT_VERSION,
        "id": normalized_id,
        "display_name": display_name,
        "description": description,
        "entrypoint": entrypoint,
        "inputs": inputs,
        "outputs": outputs,
        "actions": {"allowed": allowed},
    }


def default_contract(saltlick_id: str) -> dict[str, Any]:
    """Build a useful raw-arguments contract for a zero-config Saltlick."""
    return normalize_contract(
        {
            "contract": CONTRACT_VERSION,
            "display_name": _label_from_name(saltlick_id),
            "description": (
                "Zero-config Saltlick. Add saltlick.yaml for typed inputs and "
                "structured outputs."
            ),
            "inputs": {
                "wiki": {
                    "type": "wiki",
                    "label": "Wiki",
                    "required": True,
                    "default": {"code": "commons", "family": "commons"},
                }
            },
            "outputs": {
                "result": {
                    "type": "json",
                    "label": "Result",
                    "optional": True,
                }
            },
        },
        saltlick_id=saltlick_id,
    )


def public_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Remove image-internal entrypoint details from an API contract."""
    data = deepcopy(contract)
    data.pop("entrypoint", None)
    return data


def _normalize_wiki(value: Any, *, field_name: str) -> dict[str, str]:
    """Normalize one Pywikibot wiki code/family input."""
    data = _mapping(value, field_name=field_name)
    code = _bounded_text(
        data.get("code"),
        field_name=f"{field_name}.code",
        required=True,
        limit=32,
    ).lower()
    family = _bounded_text(
        data.get("family"),
        field_name=f"{field_name}.family",
        required=True,
        limit=32,
    ).lower()
    valid = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
    if not valid.fullmatch(code) or not valid.fullmatch(family):
        raise ValueError(f"{field_name} contains invalid wiki identifiers")
    return {"code": code, "family": family}


def _normalize_page(
    value: Any,
    *,
    field_name: str,
    namespace_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize one page value and enforce its namespace policy."""
    data = _mapping(value, field_name=field_name)
    title = _bounded_text(
        data.get("title"),
        field_name=f"{field_name}.title",
        required=True,
        limit=500,
    )
    policy = namespace_policy or {}
    namespace_raw = data.get("namespace", policy.get("default"))
    if namespace_raw is None:
        raise ValueError(f"{field_name}.namespace is required")
    namespace = int(
        _number(
            namespace_raw,
            field_name=f"{field_name}.namespace",
            integer=True,
            minimum=-2,
            maximum=5000,
        )
    )
    allowed = policy.get("allowed") or []
    if allowed and namespace not in allowed:
        raise ValueError(
            f"{field_name}.namespace must be one of "
            + ", ".join(str(item) for item in allowed)
        )
    page: dict[str, Any] = {"namespace": namespace, "title": title}
    if data.get("wiki") is not None:
        page["wiki"] = _normalize_wiki(
            data["wiki"],
            field_name=f"{field_name}.wiki",
        )
    return page


def _normalize_input_value(
    value: Any,
    *,
    name: str,
    spec: dict[str, Any],
) -> Any:
    """Dispatch one raw input value to its type-specific validator."""
    field_name = f"inputs.{name}"
    input_type = spec["type"]
    if input_type in {"string", "text", "user"}:
        return _bounded_text(
            value,
            field_name=field_name,
            required=bool(spec.get("required")),
        )
    if input_type == "integer":
        return int(
            _number(
                value,
                field_name=field_name,
                integer=True,
                minimum=spec.get("minimum"),
                maximum=spec.get("maximum"),
            )
        )
    if input_type == "number":
        return float(
            _number(
                value,
                field_name=field_name,
                integer=False,
                minimum=spec.get("minimum"),
                maximum=spec.get("maximum"),
            )
        )
    if input_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{field_name} must be a boolean")
        return value
    if input_type == "choice":
        allowed = [choice["value"] for choice in spec["choices"]]
        if value not in allowed:
            raise ValueError(f"{field_name} is not an allowed choice")
        return deepcopy(value)
    if input_type == "wiki":
        return _normalize_wiki(value, field_name=field_name)
    if input_type == "namespace":
        return int(
            _number(
                value,
                field_name=field_name,
                integer=True,
                minimum=-2,
                maximum=5000,
            )
        )
    if input_type == "page":
        return _normalize_page(
            value,
            field_name=field_name,
            namespace_policy=spec.get("namespace"),
        )
    if input_type == "pages":
        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be a list of pages")
        if len(value) > int(spec.get("max_items", MAX_PAGE_VALUES)):
            raise ValueError(
                f"{field_name} supports at most {spec['max_items']} pages"
            )
        return [
            _normalize_page(
                item,
                field_name=f"{field_name}[{index}]",
                namespace_policy=spec.get("namespace"),
            )
            for index, item in enumerate(value)
        ]
    if input_type in {"date", "datetime"}:
        text = _bounded_text(
            value,
            field_name=field_name,
            required=bool(spec.get("required")),
            limit=40,
        )
        try:
            if input_type == "date":
                date.fromisoformat(text)
            else:
                datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO {input_type}") from exc
        return text
    raise ValueError(f"{field_name} has unsupported type {input_type}")


def validate_inputs(
    contract: dict[str, Any],
    raw_inputs: Any,
) -> dict[str, Any]:
    """Validate and normalize one run's input object."""
    data = {} if raw_inputs in (None, "") else _mapping(
        raw_inputs,
        field_name="inputs",
    )
    unknown = sorted(set(data) - set(contract["inputs"]))
    if unknown:
        raise ValueError(f"unknown input(s): {', '.join(unknown)}")
    normalized: dict[str, Any] = {}
    for name, spec in contract["inputs"].items():
        if name in data:
            value = data[name]
        elif "default" in spec:
            value = deepcopy(spec["default"])
        elif spec.get("required"):
            raise ValueError(f"inputs.{name} is required")
        else:
            continue
        normalized[name] = _normalize_input_value(value, name=name, spec=spec)
    return normalized


def validate_arguments(raw_arguments: Any) -> list[str]:
    """Validate the optional compatibility escape hatch."""
    if raw_arguments in (None, ""):
        return []
    if not isinstance(raw_arguments, list):
        raise ValueError("arguments must be a list of strings")
    if len(raw_arguments) > MAX_ARGUMENTS:
        raise ValueError(f"arguments supports at most {MAX_ARGUMENTS} values")
    arguments: list[str] = []
    for index, value in enumerate(raw_arguments):
        if not isinstance(value, str):
            raise ValueError(f"arguments[{index}] must be a string")
        if len(value) > 1000:
            raise ValueError(f"arguments[{index}] exceeds 1000 characters")
        arguments.append(value)
    return arguments


def _json_safe(value: Any, *, field_name: str) -> Any:
    """Round-trip arbitrary output data through JSON-compatible values."""
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be JSON serializable") from exc


def _validate_output_value(value: Any, *, field_name: str, spec: dict[str, Any]) -> Any:
    """Validate one output value using its normalized contract type."""
    output_type = spec["type"]
    if output_type in {"string", "message"}:
        return _bounded_text(value, field_name=field_name)
    if output_type == "number":
        return _number(value, field_name=field_name, integer=False)
    if output_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{field_name} must be a boolean")
        return value
    if output_type == "page":
        return _normalize_page(value, field_name=field_name)
    if output_type == "pages":
        if not isinstance(value, list) or len(value) > MAX_PAGE_VALUES:
            raise ValueError(
                f"{field_name} must be a list of at most {MAX_PAGE_VALUES} pages"
            )
        return [
            _normalize_page(item, field_name=f"{field_name}[{index}]")
            for index, item in enumerate(value)
        ]
    if output_type == "table":
        if not isinstance(value, list) or len(value) > 10_000:
            raise ValueError(f"{field_name} must be a table with at most 10000 rows")
        rows: list[dict[str, Any]] = []
        columns = spec["columns"]
        for row_index, raw_row in enumerate(value):
            row = _mapping(raw_row, field_name=f"{field_name}[{row_index}]")
            unknown = sorted(set(row) - set(columns))
            if unknown:
                raise ValueError(
                    f"{field_name}[{row_index}] has unknown column(s): "
                    + ", ".join(unknown)
                )
            normalized_row: dict[str, Any] = {}
            for column, column_spec in columns.items():
                if column not in row:
                    if column_spec.get("optional"):
                        continue
                    raise ValueError(
                        f"{field_name}[{row_index}].{column} is required"
                    )
                normalized_row[column] = _validate_output_value(
                    row[column],
                    field_name=f"{field_name}[{row_index}].{column}",
                    spec=column_spec,
                )
            rows.append(normalized_row)
        return rows
    return _json_safe(value, field_name=field_name)


def validate_outputs(
    contract: dict[str, Any],
    raw_outputs: Any,
) -> dict[str, Any]:
    """Validate a Saltlick's structured result against its output contract."""
    data = {} if raw_outputs in (None, "") else _mapping(
        raw_outputs,
        field_name="outputs",
    )
    unknown = sorted(set(data) - set(contract["outputs"]))
    if unknown:
        raise ValueError(f"unknown output(s): {', '.join(unknown)}")
    normalized: dict[str, Any] = {}
    for name, spec in contract["outputs"].items():
        if name not in data:
            if spec.get("optional"):
                continue
            raise ValueError(f"outputs.{name} is required")
        normalized[name] = _validate_output_value(
            data[name],
            field_name=f"outputs.{name}",
            spec=spec,
        )
    return normalized


def validate_actions(
    contract: dict[str, Any],
    raw_actions: Any,
) -> list[dict[str, Any]]:
    """Validate declarative actions and enforce the contract allowlist."""
    if raw_actions in (None, ""):
        return []
    if not isinstance(raw_actions, list):
        raise ValueError("actions must be a list")
    if len(raw_actions) > MAX_PAGE_VALUES:
        raise ValueError(f"actions supports at most {MAX_PAGE_VALUES} entries")
    allowed = set(contract["actions"]["allowed"])
    normalized: list[dict[str, Any]] = []
    for index, raw_action in enumerate(raw_actions):
        action = _mapping(raw_action, field_name=f"actions[{index}]")
        action_type = str(action.get("type") or "").strip()
        if action_type not in allowed:
            raise ValueError(
                f"actions[{index}].type is not declared by this Saltlick"
            )
        target = _normalize_page(
            action.get("target"),
            field_name=f"actions[{index}].target",
        )
        params = action.get("params", {})
        if not isinstance(params, dict):
            raise ValueError(f"actions[{index}].params must be an object")
        normalized.append(
            {
                "type": action_type,
                "target": target,
                "params": _json_safe(
                    params,
                    field_name=f"actions[{index}].params",
                ),
            }
        )
    return normalized
