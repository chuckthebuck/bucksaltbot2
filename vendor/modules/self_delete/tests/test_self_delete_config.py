from self_delete.config import Settings


def test_settings_are_safe_and_bounded():
    settings = Settings.from_mapping(
        {
            "category_title": "Self delete queue",
            "dry_run": "false",
            "max_age_seconds": 999999999,
            "workers": 100,
            "max_candidates": 10000,
        }
    )

    assert settings.category_title == "Category:Self delete queue"
    assert settings.dry_run is False
    assert settings.max_age_seconds == 604800
    assert settings.workers == 16
    assert settings.max_candidates == 1000


def test_settings_default_to_dry_run():
    assert Settings.from_mapping({}).dry_run is True
