import json

from ai_manager.config.models import ThemeMode, UserSettings


def test_new_fields_default_values():
    settings = UserSettings()
    assert settings.close_to_tray is True
    assert settings.start_minimized is False
    assert settings.autostart is False
    assert settings.first_close_notice_shown is False


def test_new_fields_json_roundtrip():
    settings = UserSettings(
        theme=ThemeMode.LIGHT,
        poll_interval_ms=6000,
        close_to_tray=False,
        start_minimized=True,
        autostart=True,
        first_close_notice_shown=True,
    )
    data = json.loads(json.dumps(settings.model_dump()))
    restored = UserSettings(**data)

    assert restored == settings
    assert restored.close_to_tray is False
    assert restored.start_minimized is True
    assert restored.autostart is True
    assert restored.first_close_notice_shown is True


def test_backward_compatibility_missing_new_keys():
    """Older settings.json files omit the new keys; they must default cleanly."""
    legacy_data = {
        "theme": ThemeMode.DARK.value,
        "poll_interval_ms": 4000,
        "custom_presets": [],
    }
    restored = UserSettings(**legacy_data)

    assert restored.close_to_tray is True
    assert restored.start_minimized is False
    assert restored.autostart is False
    assert restored.first_close_notice_shown is False


def test_model_dump_contains_new_keys():
    data = UserSettings().model_dump()
    assert data["close_to_tray"] is True
    assert data["start_minimized"] is False
    assert data["autostart"] is False
    assert data["first_close_notice_shown"] is False
