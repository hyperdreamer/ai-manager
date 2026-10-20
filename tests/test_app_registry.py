import pytest
from pydantic import ValidationError

from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.config_errors import ConfigError, UnknownConfigKindError
from ai_manager.config.models import AppAIConfig, AppMetadata
from ai_manager.config.presets import DEFAULT_PRESETS
from ai_manager.config.yaml_manager import (
    ensure_config_exists,
    read_app_config,
    write_app_config,
)


def test_presets_exist():
    preset_ids = [p.id for p in DEFAULT_PRESETS]
    assert "one_api_local" in preset_ids
    assert "chat2api_local" in preset_ids
    assert "tencent_tokenhub" in preset_ids
    assert "openai_official" in preset_ids
    assert "custom" in preset_ids


def test_managed_apps(tmp_path):
    apps = get_managed_apps(tmp_path)
    assert list(apps) == ["ai-grammar", "textkit", "yt2txt", "chat2api", "file-bridge"]
    assert [a.config_kind for a in apps.values()] == [
        "llm", "llm", "llm", "chat2api", "file-bridge"
    ]
    assert "free-tts" not in apps
    assert apps["chat2api"].relative_path == tmp_path / "chat2api"
    assert apps["chat2api"].config_file_name == "config.json"
    assert apps["chat2api"].example_config_file_name == "config.example.json"
    assert apps["chat2api"].default_port == 8000
    assert apps["file-bridge"].default_port == 8964
    assert apps["textkit"].supports_split_models


@pytest.mark.parametrize("kind", [None, 1, "LLM", "file_bridge", "unknown"])
def test_bad_kind_fails_closed(tmp_path, kind):
    with pytest.raises(ValidationError, match="Unknown config_kind"):
        AppMetadata(
            id="x",
            display_name="x",
            relative_path=tmp_path,
            default_port=1,
            config_kind=kind,
        )


def test_legacy_dispatch_does_not_materialize_structured_examples(five_app_workspace):
    apps = get_managed_apps(five_app_workspace)
    for app_id in ("chat2api", "file-bridge"):
        meta = apps[app_id]
        path = meta.relative_path / meta.config_file_name
        path.unlink()
        for call in (
            lambda: ensure_config_exists(meta),
            lambda: read_app_config(meta),
            lambda: write_app_config(meta, AppAIConfig()),
        ):
            with pytest.raises(ConfigError):
                call()
        assert not path.exists()
    bad = apps["ai-grammar"].model_copy(update={"config_kind": "plugin-kind"})
    with pytest.raises(UnknownConfigKindError):
        read_app_config(bad)


def test_chat2api_preset_uses_the_backend_variable_name():
    """The editor's preset must reference the env var chat2api actually reads.

    ``CHAT2API_API_KEY`` was never read by the bridge, so picking the preset
    silently produced 401 responses. The structured schema, the auth warning and
    the shipped example config all use ``CHAT2API_TOKEN``.
    """
    preset = next(p for p in DEFAULT_PRESETS if p.id == "chat2api_local")
    assert preset.default_key_env_var == "CHAT2API_TOKEN"
    assert preset.api_base == "http://127.0.0.1:8000"
