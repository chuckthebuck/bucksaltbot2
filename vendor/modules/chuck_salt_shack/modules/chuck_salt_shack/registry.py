"""Discover immutable Saltlick directories and load their fixed entrypoints.

The registry is intentionally derived from packaged files rather than browser
state or database rows.  Build-time audit output and runtime discovery share
these functions so a deployed image cannot expose a different set of scripts
than the set a reviewer inspected.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import yaml

from .contracts import default_contract, normalize_contract, public_contract
from .safety import saltlick_rights


# Supporting both common YAML suffixes is convenient, but accepting both in
# one directory would make contract precedence ambiguous and is rejected.
SALTLICK_CONTRACT_FILENAMES = ("saltlick.yaml", "saltlick.yml")


def default_saltlicks_root() -> Path:
    """Return the packaged directory whose children are runnable Saltlicks."""
    return Path(__file__).resolve().parent / "saltlicks"


def generated_registry_path() -> Path:
    """Return the deterministic build-audit registry path."""
    return Path(__file__).resolve().parent / "generated" / "saltlick-registry.yaml"


def _source_digest(directory: Path) -> str:
    """Hash meaningful child files to identify the reviewed Saltlick source.

    Relative paths and NUL separators make the byte stream unambiguous: files
    with the same concatenated contents but different boundaries cannot share
    a digest accidentally.  Interpreter caches and hidden local tooling files
    are excluded because they are not deployed source.
    """
    digest = hashlib.sha256()
    for path in sorted(
        item
        for item in directory.rglob("*")
        if item.is_file()
        and "__pycache__" not in item.parts
        and item.suffix not in {".pyc", ".pyo"}
        and not any(part.startswith(".") for part in item.relative_to(directory).parts)
    ):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _load_raw_contract(directory: Path) -> dict[str, Any] | None:
    """Load one optional YAML mapping without applying defaults yet.

    ``None`` means the file is absent and selects the zero-config contract;
    an empty YAML file is an explicitly supplied contract and therefore still
    passes through normal contract normalization.
    """
    matches = [
        directory / filename
        for filename in SALTLICK_CONTRACT_FILENAMES
        if (directory / filename).is_file()
    ]
    if len(matches) > 1:
        raise ValueError(
            f"{directory.name} contains both saltlick.yaml and saltlick.yml"
        )
    if not matches:
        return None
    raw = yaml.safe_load(matches[0].read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{matches[0]} must contain a YAML object")
    return raw


@dataclass(frozen=True)
class SaltlickDefinition:
    """Canonical runtime identity, contract, and source location for a child.

    Instances are frozen so later request handling cannot reassign identity or
    source paths after discovery.  The normalized contract is treated as
    read-only and copied before public serialization.
    """

    id: str
    directory: Path
    contract: dict[str, Any]
    source_digest: str
    generated: bool = False

    @property
    def entrypoint_path(self) -> Path:
        """Return the entrypoint file resolved inside this Saltlick directory."""
        filename, _, _callable_name = self.contract["entrypoint"].partition(":")
        return self.directory / filename

    @property
    def callable_name(self) -> str:
        """Return the callable portion of the contract entrypoint."""
        _filename, _, callable_name = self.contract["entrypoint"].partition(":")
        return callable_name

    def as_dict(self, *, public: bool = True) -> dict[str, Any]:
        """Serialize metadata for either a browser response or image audit.

        Public responses omit the entrypoint path.  Generated rights are safe
        to expose because they are authorization identifiers, not grants.
        """
        contract = (
            public_contract(self.contract) if public else dict(self.contract)
        )
        contract["source_digest"] = self.source_digest
        contract["generated"] = bool(self.generated)
        contract["rights"] = saltlick_rights(self.id)
        return contract


def discover_saltlicks(root: Path | None = None) -> list[SaltlickDefinition]:
    """Compile immediate child directories into deterministic definitions.

    Discovery never recurses for Saltlick identities: the immediate directory
    name is the stable external ID, while deeper files are private source that
    contributes to the digest.  Hidden and underscore-prefixed directories are
    reserved for packaging support rather than runnable children.
    """
    saltlicks_root = Path(root or default_saltlicks_root()).resolve()
    if not saltlicks_root.exists():
        return []
    definitions: list[SaltlickDefinition] = []
    for directory in sorted(
        path
        for path in saltlicks_root.iterdir()
        if path.is_dir() and not path.name.startswith((".", "_"))
    ):
        raw_contract = _load_raw_contract(directory)
        # Missing YAML opts into a small generated contract.  A present YAML
        # file, including an empty one, is normalized as an authored contract.
        contract = (
            default_contract(directory.name)
            if raw_contract is None
            else normalize_contract(raw_contract, saltlick_id=directory.name)
        )
        # The normalized entrypoint grammar excludes path separators.  This
        # existence check then anchors loading to the discovered directory.
        entrypoint_filename, _, _callable_name = contract["entrypoint"].partition(":")
        entrypoint_path = directory / entrypoint_filename
        if not entrypoint_path.is_file():
            raise ValueError(
                f"{directory.name} entrypoint does not exist: "
                f"{entrypoint_filename}"
            )
        definitions.append(
            SaltlickDefinition(
                id=contract["id"],
                directory=directory,
                contract=contract,
                source_digest=_source_digest(directory),
                generated=raw_contract is None,
            )
        )
    ids = [definition.id for definition in definitions]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ValueError(
            "duplicate Saltlick ID(s): " + ", ".join(duplicates)
        )
    return definitions


def get_saltlick(
    saltlick_id: str,
    *,
    root: Path | None = None,
) -> SaltlickDefinition | None:
    """Resolve a normalized child identifier against the packaged registry."""
    normalized = str(saltlick_id or "").strip().lower().replace("-", "_")
    return next(
        (
            definition
            for definition in discover_saltlicks(root)
            if definition.id == normalized
        ),
        None,
    )


def registry_payload(root: Path | None = None) -> dict[str, Any]:
    """Build the browser catalog with all execution-only paths removed."""
    definitions = discover_saltlicks(root)
    return {
        "registry": 1,
        "module": {
            "id": "chuck_salt_shack",
            "display_name": "Salt Shack",
        },
        "saltlicks": [
            definition.as_dict(public=True) for definition in definitions
        ],
    }


def _generated_registry_payload(root: Path | None = None) -> dict[str, Any]:
    """Build the private representation checked into image audit artifacts.

    Unlike the public payload, this includes the fixed entrypoint so reviewers
    can trace a contract to the script that the worker will import.
    """
    return {
        "registry": 1,
        "module": {
            "id": "chuck_salt_shack",
            "display_name": "Salt Shack",
        },
        "saltlicks": [
            definition.as_dict(public=False)
            for definition in discover_saltlicks(root)
        ],
    }


def write_generated_registry(
    destination: Path | None = None,
    *,
    root: Path | None = None,
) -> Path:
    """Write deterministic YAML consumed for build review and image audits.

    Runtime execution still discovers packaged source directly; this file is a
    review artifact, not a second mutable source of registry truth.
    """
    target = Path(destination or generated_registry_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(
        _generated_registry_payload(root),
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )
    target.write_text(rendered, encoding="utf-8")
    return target


def generated_registry_is_current(
    destination: Path | None = None,
    *,
    root: Path | None = None,
) -> bool:
    """Return whether the checked-in registry matches current child sources."""
    target = Path(destination or generated_registry_path())
    if not target.is_file():
        return False
    current = yaml.safe_load(target.read_text(encoding="utf-8"))
    return current == _generated_registry_payload(root)


def _load_script_module(definition: SaltlickDefinition) -> ModuleType:
    """Import one fixed script under a source-digest-qualified module name.

    The path comes only from normalized image metadata.  No request value is
    interpolated into it, which is the central registry trust boundary.
    """
    module_name = (
        f"saltlick_runtime_{definition.id}_{definition.source_digest[:12]}"
    )
    spec = importlib.util.spec_from_file_location(
        module_name,
        definition.entrypoint_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Could not load Saltlick entrypoint {definition.entrypoint_path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_saltlick_callable(definition: SaltlickDefinition) -> Callable[..., Any]:
    """Load and return the immutable run callable declared by a Saltlick."""
    module = _load_script_module(definition)
    handler = getattr(module, definition.callable_name, None)
    if not callable(handler):
        raise ValueError(
            f"{definition.id} entrypoint callable is missing: "
            f"{definition.callable_name}"
        )
    return handler


def invoke_saltlick(
    definition: SaltlickDefinition,
    *,
    ctx: Any,
    inputs: dict[str, Any],
    arguments: list[str],
) -> Any:
    """Invoke the richest compatible low-boilerplate Saltlick signature.

    ``Signature.bind`` is used before the call so a ``TypeError`` raised inside
    Saltlick code is reported as the script's failure rather than mistaken for
    a request to retry the handler with fewer arguments.
    """
    handler = load_saltlick_callable(definition)
    signature = inspect.signature(handler)
    candidates = (
        (ctx, inputs, arguments),
        (ctx, inputs),
        (inputs,),
        (),
    )
    # Prefer context-aware forms: they provide authenticated site construction
    # and cancellation checks while retaining compatibility with tiny scripts.
    # A two-argument ``(inputs, arguments)`` shape cannot be distinguished by
    # ``Signature.bind`` from ``(ctx, inputs)``, so scripts that consume the
    # compatibility argument list must use the three-argument shape.
    for candidate in candidates:
        try:
            signature.bind(*candidate)
        except TypeError:
            continue
        return handler(*candidate)
    raise ValueError(
        f"{definition.id} run function must accept (), (inputs), "
        "(ctx, inputs), or (ctx, inputs, arguments)"
    )


def registry_fingerprint(root: Path | None = None) -> str:
    """Return a stable digest of the complete public browser catalog.

    This fingerprint is useful for cache/change detection.  It is separate
    from the per-run plan token, which binds normalized invocation data and the
    concrete action envelopes reviewed for one execution.
    """
    payload = registry_payload(root)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
