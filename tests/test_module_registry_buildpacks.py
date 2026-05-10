"""Tests for module buildpack metadata."""


def test_parse_module_definition_records_buildpacks():
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "rollback",
            "repo": "https://example.invalid/bucksaltbot2",
            "entry_point": "modules.rollback.blueprint",
            "ui": True,
            "buildpacks": ["heroku/python", "heroku/procfile"],
        }
    )

    assert definition.buildpacks == ("heroku/python", "heroku/procfile")
    assert definition.has_custom_buildpacks is True
