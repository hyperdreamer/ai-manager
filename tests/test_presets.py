import pytest
from pydantic import ValidationError

from ai_manager.config.models import ProviderPreset, UserSettings
from ai_manager.config.presets import DEFAULT_PRESETS, resolve_preset


def test_anthropic_preset_is_appended_with_exact_contract():
    assert [p.id for p in DEFAULT_PRESETS] == [
        "one_api_local", "chat2api_local", "tencent_tokenhub",
        "openai_official", "custom", "anthropic_official",
    ]
    preset = resolve_preset("anthropic_official")
    assert (
        preset.name, preset.api_base, preset.default_key_env_var,
        preset.endpoint, preset.docs_url, preset.description,
    ) == (
        "Official Anthropic API", "https://api.anthropic.com", "ANTHROPIC_API_KEY",
        "/v1/messages", "https://docs.anthropic.com",
        "Claude models over the Anthropic Messages protocol",
    )
    assert all(p.endpoint is None for p in DEFAULT_PRESETS[:-1])
    assert resolve_preset("missing") is None
    with pytest.raises(ValueError):
        ProviderPreset(id="bad", name="Bad", api_base="https://x", endpoint="/bad")


def test_resolver_returns_first_match_without_mutating_supplied_sequence():
    first = ProviderPreset(id="x", name="First", api_base="https://first")
    second = ProviderPreset(id="x", name="Second", api_base="https://second")
    offered = [first, second]
    assert resolve_preset("x", presets=offered) is first
    assert offered == [first, second]
    assert resolve_preset("x", presets=[]) is None
    assert resolve_preset("missing", presets=offered) is None
    assert resolve_preset("one_api_local") is DEFAULT_PRESETS[0]


@pytest.mark.parametrize("endpoint", [
    "/bad", "", " /v1/messages", "/v1/messages/", "https://x/v1/messages",
    "transport-only", 42,
])
def test_persisted_custom_preset_rejects_unsupported_endpoint(endpoint):
    with pytest.raises(ValidationError) as caught:
        UserSettings.model_validate({"custom_presets": [{
            "id": "local", "name": "Local", "api_base": "https://local",
            "endpoint": endpoint,
        }]})
    assert [(error["loc"], error["type"]) for error in caught.value.errors()] == [
        (("custom_presets", 0, "endpoint"), "literal_error"),
    ]


@pytest.mark.parametrize("endpoint", [
    None, "/v1/chat/completions", "/v1/responses", "/v1/messages",
])
def test_persisted_custom_preset_loads_optional_typed_endpoint(endpoint):
    data = {"id": "local", "name": "Local", "api_base": "https://local"}
    legacy = UserSettings.model_validate({"custom_presets": [data]})
    assert legacy.custom_presets[0].endpoint is None
    data["endpoint"] = endpoint
    settings = UserSettings.model_validate({"custom_presets": [data]})
    assert settings.custom_presets[0].endpoint == endpoint
