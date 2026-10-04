from pathlib import Path
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.presets import DEFAULT_PRESETS


def test_presets_exist():
    preset_ids = [p.id for p in DEFAULT_PRESETS]
    assert "one_api_local" in preset_ids
    assert "chat2api_local" in preset_ids
    assert "tencent_tokenhub" in preset_ids
    assert "openai_official" in preset_ids
    assert "custom" in preset_ids


def test_managed_apps(tmp_path):
    apps = get_managed_apps(tmp_path)
    assert set(apps.keys()) == {"ai-grammar", "textkit", "yt2txt"}
    assert "free-tts" not in apps
    assert "file-bridge" not in apps

    assert apps["textkit"].supports_split_models is True
    assert apps["ai-grammar"].supports_split_models is False
    assert apps["yt2txt"].default_port == 8666
