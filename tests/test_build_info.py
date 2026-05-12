"""Tests for deployment build metadata shown in the footer."""

from router.build_info import _module_build_info, deployment_build_info


def test_deployment_build_info_includes_framework_and_four_award():
    deployment_build_info.cache_clear()
    info = deployment_build_info()

    assert info.framework.version is not None
    assert info.framework.commit is not None

    modules = {module.name: module for module in info.modules}
    assert modules["four_award"].version == "0.1.2"
    assert modules["four_award"].commit == "b777437"


def test_module_build_info_reads_subtree_metadata(tmp_path):
    module_root = tmp_path / "example"
    module_root.mkdir()
    (module_root / "SUBTREE.md").write_text(
        "\n".join(
            [
                "# Vendored Module Snapshot",
                "",
                "- Snapshot commit: `abc1234`",
                "- Module version: `1.2.3`",
                "- Framework module name: `example_module`",
            ]
        ),
        encoding="utf-8",
    )

    info = _module_build_info(module_root)

    assert info is not None
    assert info.name == "example_module"
    assert info.version == "1.2.3"
    assert info.commit == "abc1234"
