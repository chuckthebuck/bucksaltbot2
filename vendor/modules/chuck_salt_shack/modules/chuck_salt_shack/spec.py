"""Validated Saltlick workflow specification."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import re
from typing import Any

from .expressions import parse_expression


SPEC_VERSION = 1
MAX_SOURCE_PAGES = 500
MAX_TRANSFORMS = 20
SOURCE_TYPES = {
    "titles",
    "category",
    "backlinks",
    "links",
    "search",
    "user_contribs",
    "recent_changes",
    "prefix",
}
TRANSFORM_TYPES = {
    "literal_replace",
    "regex_replace",
    "prepend",
    "append",
    "set_text",
    "template",
    "expression",
}
INVOCATION_INPUTS = {"titles", "target"}
INVOCATION_ARGUMENTS = {
    "source_limit",
    "namespaces",
    "max_edits",
    "title_regex",
    "contains",
    "not_contains",
    "summary",
    "throttle_seconds",
}
_REGEX_FLAGS = {"i", "m", "s", "x"}


def _string(value: Any, *, field_name: str, limit: int = 20_000) -> str:
    """Normalize a bounded recipe string."""
    text = str(value or "")
    if len(text) > limit:
        raise ValueError(f"{field_name} exceeds {limit} characters")
    return text


def _bool(value: Any, *, default: bool = False) -> bool:
    """Coerce common configuration representations into a boolean."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off", ""}:
            return False
    raise ValueError("boolean setting has an invalid value")


def _integer(
    value: Any,
    *,
    field_name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Coerce and bound one integer recipe field."""
    try:
        parsed = default if value is None else int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(
            f"{field_name} must be between {minimum} and {maximum}"
        )
    return parsed


def _namespaces(value: Any) -> tuple[int, ...]:
    """Normalize a comma-separated or list namespace selection."""
    if value in (None, ""):
        return ()
    raw_values = value if isinstance(value, (list, tuple)) else str(value).split(",")
    parsed = []
    for raw_value in raw_values:
        namespace = _integer(
            raw_value,
            field_name="source.namespaces",
            default=0,
            minimum=-2,
            maximum=5000,
        )
        if namespace not in parsed:
            parsed.append(namespace)
    return tuple(parsed)


@dataclass(frozen=True)
class WikiSpec:
    """Validated Pywikibot site coordinates."""

    code: str = "commons"
    family: str = "commons"

    @classmethod
    def from_dict(cls, raw: Any) -> "WikiSpec":
        """Normalize wiki code and family from recipe data."""
        data = raw if isinstance(raw, dict) else {}
        code = _string(data.get("code") or "commons", field_name="wiki.code", limit=32).strip()
        family = _string(
            data.get("family") or "commons",
            field_name="wiki.family",
            limit=32,
        ).strip()
        valid = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
        if not valid.fullmatch(code) or not valid.fullmatch(family):
            raise ValueError("wiki code and family must use lowercase site identifiers")
        return cls(code=code, family=family)


@dataclass(frozen=True)
class SourceSpec:
    """Bounded page-generator configuration for a legacy workflow recipe."""

    type: str = "titles"
    titles: tuple[str, ...] = ()
    target: str = ""
    limit: int = 25
    namespaces: tuple[int, ...] = ()
    recursive: int = 0
    only_template_inclusion: bool = False

    @classmethod
    def from_dict(cls, raw: Any) -> "SourceSpec":
        """Validate a source generator and its page limit."""
        if not isinstance(raw, dict):
            raise ValueError("source must be an object")
        source_type = _string(
            raw.get("type") or "titles",
            field_name="source.type",
            limit=32,
        ).strip().lower()
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source type: {source_type}")
        limit = _integer(
            raw.get("limit"),
            field_name="source.limit",
            default=25,
            minimum=1,
            maximum=MAX_SOURCE_PAGES,
        )
        titles_raw = raw.get("titles") or []
        if isinstance(titles_raw, str):
            titles_raw = titles_raw.splitlines()
        if not isinstance(titles_raw, list):
            raise ValueError("source.titles must be a list or newline-delimited text")
        titles = tuple(
            dict.fromkeys(
                title
                for title in (
                    _string(item, field_name="source title", limit=500).strip()
                    for item in titles_raw
                )
                if title
            )
        )
        if len(titles) > MAX_SOURCE_PAGES:
            raise ValueError(f"source.titles supports at most {MAX_SOURCE_PAGES} pages")
        target = _string(
            raw.get("target"),
            field_name="source.target",
            limit=1000,
        ).strip()
        if source_type == "titles" and not titles:
            raise ValueError("titles source requires at least one page title")
        if source_type != "titles" and source_type != "recent_changes" and not target:
            raise ValueError(f"{source_type} source requires a target")
        namespaces = _namespaces(raw.get("namespaces"))
        if source_type == "prefix" and len(namespaces) > 1:
            raise ValueError("prefix source accepts one namespace")
        return cls(
            type=source_type,
            titles=titles,
            target=target,
            limit=min(limit, len(titles)) if source_type == "titles" else limit,
            namespaces=namespaces,
            recursive=_integer(
                raw.get("recursive"),
                field_name="source.recursive",
                default=0,
                minimum=0,
                maximum=5,
            ),
            only_template_inclusion=_bool(raw.get("only_template_inclusion")),
        )


@dataclass(frozen=True)
class FilterSpec:
    """Read-only filters applied before workflow transformations."""

    title_regex: str = ""
    contains: str = ""
    not_contains: str = ""
    skip_redirects: bool = True
    skip_missing: bool = True

    @classmethod
    def from_dict(cls, raw: Any) -> "FilterSpec":
        """Validate optional title and content filters."""
        data = raw if isinstance(raw, dict) else {}
        title_regex = _string(
            data.get("title_regex"),
            field_name="filters.title_regex",
            limit=2000,
        )
        if title_regex:
            try:
                re.compile(title_regex)
            except re.error as exc:
                raise ValueError(f"invalid title regex: {exc}") from exc
        return cls(
            title_regex=title_regex,
            contains=_string(
                data.get("contains"),
                field_name="filters.contains",
            ),
            not_contains=_string(
                data.get("not_contains"),
                field_name="filters.not_contains",
            ),
            skip_redirects=_bool(data.get("skip_redirects"), default=True),
            skip_missing=_bool(data.get("skip_missing"), default=True),
        )


@dataclass(frozen=True)
class TransformSpec:
    """One validated text transformation in a legacy workflow."""

    type: str
    find: str = ""
    replace: str = ""
    text: str = ""
    pattern: str = ""
    flags: str = ""
    count: int = 0
    expression: str = ""

    @classmethod
    def from_dict(cls, raw: Any, index: int) -> "TransformSpec":
        """Validate a transformation and report errors with its list index."""
        if not isinstance(raw, dict):
            raise ValueError(f"transform {index} must be an object")
        transform_type = _string(
            raw.get("type"),
            field_name=f"transform {index} type",
            limit=32,
        ).strip().lower()
        if transform_type not in TRANSFORM_TYPES:
            raise ValueError(f"unsupported transform type: {transform_type}")
        find = _string(raw.get("find"), field_name=f"transform {index} find")
        replacement = _string(
            raw.get("replace", raw.get("replacement")),
            field_name=f"transform {index} replace",
        )
        text = _string(raw.get("text"), field_name=f"transform {index} text")
        pattern = _string(
            raw.get("pattern", find),
            field_name=f"transform {index} pattern",
            limit=4000,
        )
        flags = _string(
            raw.get("flags"),
            field_name=f"transform {index} flags",
            limit=8,
        ).lower()
        invalid_flags = sorted(set(flags) - _REGEX_FLAGS)
        if invalid_flags:
            raise ValueError(
                f"transform {index} has unsupported regex flags: "
                + "".join(invalid_flags)
            )
        count = _integer(
            raw.get("count"),
            field_name=f"transform {index} count",
            default=0,
            minimum=0,
            maximum=1_000_000,
        )
        expression = _string(
            raw.get("expression"),
            field_name=f"transform {index} expression",
            limit=4000,
        )
        if transform_type == "literal_replace" and not find:
            raise ValueError(f"transform {index} requires find text")
        if transform_type == "regex_replace":
            if not pattern:
                raise ValueError(f"transform {index} requires a regex pattern")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"transform {index} has invalid regex: {exc}") from exc
        if transform_type in {"prepend", "append", "set_text", "template"} and not text:
            raise ValueError(f"transform {index} requires text")
        if transform_type == "expression":
            parse_expression(expression)
        return cls(
            type=transform_type,
            find=find,
            replace=replacement,
            text=text,
            pattern=pattern,
            flags=flags,
            count=count,
            expression=expression,
        )


@dataclass(frozen=True)
class SaveSpec:
    """Edit metadata and pacing controls for legacy workflow saves."""

    summary: str = "Saltlick workflow"
    minor: bool = False
    bot: bool = True
    watch: str = "nochange"
    throttle_seconds: float = 0.0

    @classmethod
    def from_dict(cls, raw: Any) -> "SaveSpec":
        """Validate edit-summary, watchlist, and throttle settings."""
        data = raw if isinstance(raw, dict) else {}
        summary = _string(
            data.get("summary") or "Saltlick workflow",
            field_name="save.summary",
            limit=500,
        ).strip()
        watch = _string(
            data.get("watch") or "nochange",
            field_name="save.watch",
            limit=16,
        ).strip().lower()
        if watch not in {"watch", "unwatch", "preferences", "nochange"}:
            raise ValueError("save.watch has an unsupported value")
        try:
            throttle = float(data.get("throttle_seconds") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("save.throttle_seconds must be a number") from exc
        if throttle < 0 or throttle > 60:
            raise ValueError("save.throttle_seconds must be between 0 and 60")
        return cls(
            summary=summary,
            minor=_bool(data.get("minor")),
            bot=_bool(data.get("bot"), default=True),
            watch=watch,
            throttle_seconds=throttle,
        )


@dataclass(frozen=True)
class LimitSpec:
    """Hard execution limits that keep legacy workflows bounded."""

    max_edits: int = 25
    stop_on_error: bool = False
    max_page_bytes: int = 2_000_000

    @classmethod
    def from_dict(cls, raw: Any, *, source_limit: int) -> "LimitSpec":
        """Validate execution limits relative to the selected source."""
        data = raw if isinstance(raw, dict) else {}
        return cls(
            max_edits=_integer(
                data.get("max_edits"),
                field_name="limits.max_edits",
                default=min(25, source_limit),
                minimum=1,
                maximum=MAX_SOURCE_PAGES,
            ),
            stop_on_error=_bool(data.get("stop_on_error")),
            max_page_bytes=_integer(
                data.get("max_page_bytes"),
                field_name="limits.max_page_bytes",
                default=2_000_000,
                minimum=1_000,
                maximum=10_000_000,
            ),
        )


@dataclass(frozen=True)
class WorkflowSpec:
    """Canonical, immutable legacy workflow recipe."""

    version: int
    name: str
    wiki: WikiSpec
    source: SourceSpec
    filters: FilterSpec
    transforms: tuple[TransformSpec, ...]
    save: SaveSpec
    limits: LimitSpec
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Any) -> "WorkflowSpec":
        """Validate raw recipe data into a complete workflow specification."""
        if not isinstance(raw, dict):
            raise ValueError("workflow spec must be an object")
        version = _integer(
            raw.get("version"),
            field_name="version",
            default=SPEC_VERSION,
            minimum=SPEC_VERSION,
            maximum=SPEC_VERSION,
        )
        name = _string(
            raw.get("name") or "my_saltlick_bot",
            field_name="name",
            limit=80,
        ).strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{1,79}", name):
            raise ValueError(
                "name must start with a letter and use letters, numbers, "
                "spaces, _ or -"
            )
        source = SourceSpec.from_dict(raw.get("source"))
        transforms_raw = raw.get("transforms")
        if not isinstance(transforms_raw, list) or not transforms_raw:
            raise ValueError("workflow requires at least one transform")
        if len(transforms_raw) > MAX_TRANSFORMS:
            raise ValueError(f"workflow supports at most {MAX_TRANSFORMS} transforms")
        transforms = tuple(
            TransformSpec.from_dict(item, index)
            for index, item in enumerate(transforms_raw, start=1)
        )
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        return cls(
            version=version,
            name=name,
            wiki=WikiSpec.from_dict(raw.get("wiki")),
            source=source,
            filters=FilterSpec.from_dict(raw.get("filters")),
            transforms=transforms,
            save=SaveSpec.from_dict(raw.get("save")),
            limits=LimitSpec.from_dict(raw.get("limits"), source_limit=source.limit),
            metadata=dict(metadata),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe canonical specification."""
        return asdict(self)


def recipe_with_invocation(
    recipe: Any,
    *,
    inputs: Any = None,
    arguments: Any = None,
) -> dict[str, Any]:
    """Apply a small, explicit invocation overlay to recipe data.

    Generated bots bake in the recipe and accept only these inputs/arguments at
    their run endpoint. No handler path or Python source is accepted here.
    """
    if not isinstance(recipe, dict):
        raise ValueError("recipe must be an object")
    input_values = inputs if isinstance(inputs, dict) else {}
    argument_values = arguments if isinstance(arguments, dict) else {}
    if inputs is not None and not isinstance(inputs, dict):
        raise ValueError("inputs must be an object")
    if arguments is not None and not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    unknown_inputs = sorted(set(input_values) - INVOCATION_INPUTS)
    unknown_arguments = sorted(set(argument_values) - INVOCATION_ARGUMENTS)
    if unknown_inputs:
        raise ValueError(f"unsupported invocation input(s): {', '.join(unknown_inputs)}")
    if unknown_arguments:
        raise ValueError(
            f"unsupported invocation argument(s): {', '.join(unknown_arguments)}"
        )

    merged = deepcopy(recipe)
    source = merged.setdefault("source", {})
    filters = merged.setdefault("filters", {})
    save = merged.setdefault("save", {})
    limits = merged.setdefault("limits", {})
    if "titles" in input_values:
        source["titles"] = input_values["titles"]
    if "target" in input_values:
        source["target"] = input_values["target"]
    source_mapping = {
        "source_limit": "limit",
        "namespaces": "namespaces",
    }
    filter_mapping = {
        "title_regex": "title_regex",
        "contains": "contains",
        "not_contains": "not_contains",
    }
    save_mapping = {
        "summary": "summary",
        "throttle_seconds": "throttle_seconds",
    }
    limit_mapping = {"max_edits": "max_edits"}
    for input_name, target_name in source_mapping.items():
        if input_name in argument_values:
            source[target_name] = argument_values[input_name]
    for input_name, target_name in filter_mapping.items():
        if input_name in argument_values:
            filters[target_name] = argument_values[input_name]
    for input_name, target_name in save_mapping.items():
        if input_name in argument_values:
            save[target_name] = argument_values[input_name]
    for input_name, target_name in limit_mapping.items():
        if input_name in argument_values:
            limits[target_name] = argument_values[input_name]
    return merged
