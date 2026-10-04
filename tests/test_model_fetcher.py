import pytest
import respx
import httpx
from ai_manager.config.models import ModelFetchRequest
from ai_manager.services.model_fetcher import fetch_models_sync


@respx.mock
def test_fetch_models_standard_openai():
    respx.get("http://localhost:3000/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gemini-flash-high"},
                    {"id": "gpt-5.6-terra"},
                    {"id": "deepseek-flash"},
                ]
            },
        )
    )

    req = ModelFetchRequest(token=1, api_base="http://localhost:3000", api_key="sk-test")
    resp = fetch_models_sync(req)
    assert resp.success is True
    assert resp.token == 1
    assert "gemini-flash-high" in resp.models
    assert "gpt-5.6-terra" in resp.models
    assert resp.endpoint_used == "http://localhost:3000/v1/models"


@respx.mock
def test_fetch_models_fallback_endpoint():
    # 404 on /v1/models
    respx.get("http://localhost:11434/v1/models").mock(
        return_value=httpx.Response(404)
    )
    # 200 on /models
    respx.get("http://localhost:11434/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {"name": "llama3:latest"},
                    {"name": "qwen2.5:32b"},
                ]
            },
        )
    )

    req = ModelFetchRequest(token=2, api_base="http://localhost:11434", api_key="")
    resp = fetch_models_sync(req)
    assert resp.success is True
    assert resp.token == 2
    assert "llama3:latest" in resp.models
    assert resp.endpoint_used == "http://localhost:11434/models"


@respx.mock
def test_fetch_models_unauthorized():
    respx.get("https://api.openai.com/v1/models").mock(
        return_value=httpx.Response(401, json={"error": "Invalid API key"})
    )

    req = ModelFetchRequest(token=3, api_base="https://api.openai.com", api_key="sk-bad")
    resp = fetch_models_sync(req)
    assert resp.success is False
    assert "401" in (resp.error_message or "")
