from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from ai_manager.config.models import (
    AppAIConfig,
    AppMetadata,
    ConfigSnapshot,
    ModelFetchRequest,
    ProviderPreset,
    ServiceRunState,
    ServiceStatus,
    SupervisorStatus,
    ThemeMode,
)


def test_app_ai_config_single_model():
    cfg = AppAIConfig(
        api_base="http://localhost:3000",
        api_key="sk-test",
        model="gpt-4o",
    )
    assert not cfg.is_split_model
    assert cfg.get_display_model() == "gpt-4o"


def test_app_ai_config_split_model():
    cfg = AppAIConfig(
        api_base="http://localhost:3000",
        api_key="sk-test",
        is_split_model=True,
        ocr_model="qwen-flash",
        text_model="deepseek-v3",
    )
    assert cfg.is_split_model
    assert "OCR: qwen-flash" in cfg.get_display_model()
    assert "Text: deepseek-v3" in cfg.get_display_model()


def test_supervisor_status_serialization():
    status = SupervisorStatus(
        is_running=True,
        supervisor_pid=1234,
        services={
            "ai-grammar": ServiceStatus(
                service_id="ai-grammar",
                state=ServiceRunState.RUNNING,
                pid=5678,
                log_path="/tmp/ai-grammar.log",
            )
        },
        timestamp="2026-10-04 12:00:00",
    )
    data = status.model_dump()
    assert data["is_running"] is True
    assert data["services"]["ai-grammar"]["pid"] == 5678


def test_metadata_default_and_llm_equality(tmp_path):
    assert AppMetadata(
        id="x", display_name="x", relative_path=tmp_path, default_port=1
    ).config_kind == "llm"
    cfg = AppAIConfig(model="original")
    assert cfg == cfg.model_copy(deep=True)
    assert cfg != cfg.model_copy(update={"model": "changed"})


@pytest.mark.parametrize("origin", [None, "", 7])
def test_fetch_origin_is_required_and_strict(origin):
    with pytest.raises(ValidationError):
        ModelFetchRequest(
            token=1, api_base="http://localhost", api_key="", app_id=origin
        )
    with pytest.raises(ValidationError):
        ModelFetchRequest(token=1, api_base="http://localhost", api_key="")


@pytest.mark.parametrize(
    "value", ["", " /v1/messages", "/v1/other", "https://x/v1/messages", 42, True]
)
@pytest.mark.parametrize(
    "cls,fields",
    [
        (AppAIConfig, {}),
        (ProviderPreset, {"id": "x", "name": "X", "api_base": "https://x"}),
    ],
)
def test_endpoint_literal_rejects_non_vocabulary(cls, fields, value):
    with pytest.raises(ValidationError) as caught:
        cls(**fields, endpoint=value)
    assert any(
        e["loc"] == ("endpoint",) and e["type"] == "literal_error"
        for e in caught.value.errors()
    )


def test_canonical_values_clear_only_inactive_models():
    unified = AppAIConfig(
        api_base=" https://x/ ",
        api_key=" $TOKEN ",
        model=" ",
        ocr_model="hidden",
        text_model="hidden",
    )
    assert (unified.api_base, unified.api_key) == ("https://x/", "$TOKEN")
    assert (unified.model, unified.ocr_model, unified.text_model) == (None, None, None)
    split = AppAIConfig(
        is_split_model=True, model="hidden", ocr_model=" ocr ", text_model=" "
    )
    assert (split.model, split.ocr_model, split.text_model) == (None, "ocr", None)
    assert split.get_display_model() == "OCR: ocr | Text: none"
    assert AppAIConfig(endpoint_raw="None").endpoint_raw == "None"
    assert AppAIConfig().endpoint is None
    req = ModelFetchRequest(
        token=1, app_id="a", api_base="x", api_key="", endpoint="transport-only"
    )
    assert req.endpoint == "transport-only"
    with pytest.raises(ValidationError):
        AppAIConfig(api_base={})


def test_snapshot_is_validated_and_owns_configuration():
    config = AppAIConfig(model="old")
    saved = ConfigSnapshot(config, b"d" * 32, False)
    config.model = "new"
    assert saved.config.model == "old"
    with pytest.raises(FrozenInstanceError):
        saved.api_base_present = True
    for args, message in [
        (({}, b"d" * 32, False), "Snapshot config must be an AppAIConfig."),
        ((AppAIConfig(), "d" * 32, False), "Snapshot digest must be a 32-byte SHA-256 value."),
        ((AppAIConfig(), b"d", False), "Snapshot digest must be a 32-byte SHA-256 value."),
        ((AppAIConfig(), b"d" * 32, 1), "Snapshot base presence must be a boolean."),
    ]:
        with pytest.raises(ValueError, match="^" + __import__("re").escape(message) + "$"):
            ConfigSnapshot(*args)


def test_snapshot_factory_installs_explicit_digest_and_presence():
    from tests.endpoint_helpers import snapshot

    built = snapshot(present=False)
    assert built.config == AppAIConfig()
    assert built.sha256 == b"s" * 32
    assert built.api_base_present is False
