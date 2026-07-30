import shutil

import pytest

from chuck_salt_shack.contracts import normalize_contract, validate_inputs
from chuck_salt_shack.registry import (
    discover_saltlicks,
    generated_registry_is_current,
    get_saltlick,
    write_generated_registry,
)


def test_page_input_requires_and_normalizes_allowed_namespace():
    definition = get_saltlick("page_purger")
    assert definition is not None

    inputs = validate_inputs(
        definition.contract,
        {
            "targets": [
                {"title": "Sandbox", "namespace": 2},
                {"title": "Example", "namespace": 10},
            ]
        },
    )

    assert inputs["wiki"] == {"code": "commons", "family": "commons"}
    assert inputs["targets"] == [
        {"title": "Sandbox", "namespace": 2},
        {"title": "Example", "namespace": 10},
    ]
    assert inputs["force_link_update"] is True

    with pytest.raises(ValueError, match="must be one of"):
        validate_inputs(
            definition.contract,
            {"targets": [{"title": "Bad namespace", "namespace": 828}]},
        )


def test_duplicated_directory_is_discovered_without_central_registration(tmp_path):
    source = tmp_path / "first_report"
    source.mkdir()
    (source / "script.py").write_text(
        "def run(inputs):\n    return {'outputs': {}}\n",
        encoding="utf-8",
    )
    copied = tmp_path / "second_report"
    shutil.copytree(source, copied)

    definitions = discover_saltlicks(tmp_path)

    assert [definition.id for definition in definitions] == [
        "first_report",
        "second_report",
    ]
    assert all(definition.generated for definition in definitions)


def test_generated_registry_tracks_discovered_directories(tmp_path):
    saltlick_root = tmp_path / "saltlicks"
    saltlick_root.mkdir()
    directory = saltlick_root / "one_report"
    directory.mkdir()
    (directory / "script.py").write_text(
        "def run(inputs):\n    return {'outputs': {}}\n",
        encoding="utf-8",
    )
    output = tmp_path / "registry.yaml"

    write_generated_registry(output, root=saltlick_root)

    assert generated_registry_is_current(output, root=saltlick_root)
    second = saltlick_root / "another_report"
    shutil.copytree(directory, second)
    assert not generated_registry_is_current(output, root=saltlick_root)


def test_checked_in_registry_is_current():
    assert generated_registry_is_current()


def test_page_and_namespace_inputs_link_to_the_only_wiki_input():
    contract = normalize_contract(
        {
            "inputs": {
                "project": {"type": "wiki"},
                "article": {"type": "page"},
                "namespace": {"type": "namespace"},
            }
        },
        saltlick_id="linked_inputs",
    )

    assert contract["inputs"]["article"]["wiki_input"] == "project"
    assert contract["inputs"]["namespace"]["wiki_input"] == "project"


def test_explicit_wiki_input_must_reference_a_wiki():
    with pytest.raises(ValueError, match="must name a wiki input"):
        normalize_contract(
            {
                "inputs": {
                    "project": {"type": "string"},
                    "article": {
                        "type": "page",
                        "wiki_input": "project",
                    },
                }
            },
            saltlick_id="bad_link",
        )
