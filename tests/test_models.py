import pytest
from ai_manager.config.models import (
    AppAIConfig,
    AppMetadata,
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
