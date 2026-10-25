import pytest
import respx
import httpx
from ai_manager.config.models import ModelFetchRequest
from ai_manager.services.model_fetcher import ModelFetchWorker, fetch_models_sync


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

    req = ModelFetchRequest(
        token=1, api_base="http://localhost:3000", api_key="sk-test", app_id="ai-grammar"
    )
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

    req = ModelFetchRequest(
        token=2, api_base="http://localhost:11434", api_key="", app_id="textkit"
    )
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

    req = ModelFetchRequest(
        token=3, api_base="https://api.openai.com", api_key="sk-bad", app_id="yt2txt"
    )
    resp = fetch_models_sync(req)
    assert resp.success is False
    assert "401" in (resp.error_message or "")


@pytest.mark.parametrize("endpoint", [
    None, "/v1/chat/completions", "/v1/responses", "/v1/messages", "transport-only",
])
@pytest.mark.parametrize("raw_key,resolved", [
    ("literal", "literal"), ("$EP_UNSET_KEY", ""), ("", ""),
    ("$EP_SET_KEY", "resolved-secret"),
])
@respx.mock
def test_discovery_auth_preserves_urls(endpoint, raw_key, resolved, monkeypatch):
    monkeypatch.delenv("EP_UNSET_KEY", raising=False)
    monkeypatch.setenv("EP_SET_KEY", "resolved-secret")
    first = respx.get("https://x/v1/models").mock(return_value=httpx.Response(404))
    fallback = respx.get("https://x/models").mock(return_value=httpx.Response(
        200, json={"data": [{"id": "Z"}, {"id": "a"}, {"id": "Z"}]},
    ))
    request = ModelFetchRequest(
        token=31, app_id="textkit", api_base="https://x/", api_key=raw_key,
        endpoint=endpoint,
    )
    before = request.model_dump()
    response = fetch_models_sync(request)
    assert response.success and response.token == 31
    assert response.endpoint_used == "https://x/models" and response.models == ["a", "Z"]
    assert request.model_dump() == before
    assert [str(call.request.url) for call in respx.calls] == [
        "https://x/v1/models", "https://x/models",
    ]
    for route in (first, fallback):
        headers = route.calls[0].request.headers
        assert headers["Accept"] == "application/json"
        assert headers["User-Agent"] == "ai-manager/0.1.0"
        if endpoint == "/v1/messages":
            assert "authorization" not in headers
            assert headers.get("x-api-key") == resolved
            assert headers.get("anthropic-version") == "2023-06-01"
        else:
            assert "x-api-key" not in headers and "anthropic-version" not in headers
            assert headers.get("authorization") == ("Bearer " + resolved if resolved else None)


@respx.mock
def test_model_worker_owns_complete_request_and_uses_captured_endpoint(qapp):
    request = ModelFetchRequest(
        token=41, app_id="textkit", api_base="https://captured", api_key="captured-key",
        endpoint="/v1/messages",
    )
    worker = ModelFetchWorker(request)
    request.token = 99
    request.app_id = "ai-grammar"
    request.api_base = "https://mutated"
    request.api_key = "mutated-key"
    request.endpoint = "/v1/responses"
    assert worker.request.model_dump() == {
        "token": 41, "app_id": "textkit", "api_base": "https://captured",
        "api_key": "captured-key", "endpoint": "/v1/messages",
    }
    assert worker.request is not request
    route = respx.get("https://captured/v1/models").mock(return_value=httpx.Response(
        200, json=["claude-test"],
    ))
    responses = []
    worker.signals.finished.connect(responses.append)
    worker.run()
    assert len(responses) == 1
    assert responses[0].model_dump() == {
        "token": 41, "success": True, "models": ["claude-test"],
        "error_message": None, "endpoint_used": "https://captured/v1/models",
    }
    headers = route.calls[0].request.headers
    assert headers["x-api-key"] == "captured-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in headers


@pytest.mark.parametrize("endpoint", [None, "/v1/messages"])
@pytest.mark.parametrize("failure,expected,count", [
    ("unauthorized", "HTTP 401 Unauthorized: Invalid or missing API key at https://x/v1/models", 1),
    ("not-found", "HTTP 404 Not Found at https://x/models", 2),
    ("server", "HTTP 503 (Service Unavailable) from https://x/models", 2),
    ("json", "Invalid JSON received from https://x/models: Expecting value: line 1 column 1 (char 0)", 2),
    ("connect", "Connection refused connecting to https://x/models", 2),
    ("timeout", "Request timed out connecting to https://x/models", 2),
    ("network", "Network error connecting to https://x/models: fixture network", 2),
])
@respx.mock
def test_discovery_preserves_error_copy_and_fallback(endpoint, failure, expected, count):
    def respond(request):
        if failure == "unauthorized":
            return httpx.Response(401)
        if failure == "not-found":
            return httpx.Response(404)
        if failure == "server":
            return httpx.Response(503)
        if failure == "json":
            return httpx.Response(200, text="not-json")
        if failure == "connect":
            raise httpx.ConnectError("fixture connect", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        raise RuntimeError("fixture network")

    respx.get("https://x/v1/models").mock(side_effect=respond)
    if count == 2:
        respx.get("https://x/models").mock(side_effect=respond)
    response = fetch_models_sync(ModelFetchRequest(
        token=51, app_id="ai-grammar", api_base="https://x/", api_key="literal",
        endpoint=endpoint,
    ))
    assert response.model_dump() == {
        "token": 51, "success": False, "models": [],
        "error_message": expected, "endpoint_used": None,
    }
    assert [str(call.request.url) for call in respx.calls] == [
        "https://x/v1/models", "https://x/models",
    ][:count]


@pytest.mark.parametrize("payload,expected", [
    ({"data": [{"id": "Z"}, {"id": "a"}, "a", {"id": 123}, {}]}, ["123", "a", "Z"]),
    ({"models": [{"name": "Z"}, "a", {"name": "Z"}, {}]}, ["a", "Z"]),
    ([{"id": "Z"}, "a", {"id": "Z"}, None], ["a", "Z"]),
    ({"unexpected": []}, []),
])
@respx.mock
def test_discovery_preserves_payload_normalization(payload, expected):
    respx.get("https://x/v1/models").mock(return_value=httpx.Response(200, json=payload))
    response = fetch_models_sync(ModelFetchRequest(
        token=61, app_id="textkit", api_base="https://x", api_key="", endpoint="/v1/messages",
    ))
    assert response.success and response.token == 61
    assert response.models == expected
    assert response.endpoint_used == "https://x/v1/models"


@respx.mock
def test_discovery_keeps_timeout_redirects_and_historical_v1_path(monkeypatch):
    original_client = httpx.Client
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return original_client(**kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    first = respx.get("https://x/v1/v1/models").mock(return_value=httpx.Response(404))
    respx.get("https://x/v1/models").mock(return_value=httpx.Response(
        302, headers={"Location": "https://x/redirected"},
    ))
    respx.get("https://x/redirected").mock(return_value=httpx.Response(200, json=["a"]))
    response = fetch_models_sync(ModelFetchRequest(
        token=71, app_id="textkit", api_base="https://x/v1/", api_key="literal",
        endpoint="/v1/messages",
    ))
    assert response.success and response.token == 71 and response.models == ["a"]
    assert response.endpoint_used == "https://x/v1/models"
    assert len(options) == 1
    assert options[0]["follow_redirects"] is True
    assert options[0]["timeout"] == httpx.Timeout(10.0, connect=5.0)
    assert first.calls[0].request.extensions["timeout"] == {
        "connect": 5.0, "read": 10.0, "write": 10.0, "pool": 10.0,
    }
    assert [str(call.request.url) for call in respx.calls] == [
        "https://x/v1/v1/models", "https://x/v1/models", "https://x/redirected",
    ]


@pytest.mark.parametrize("endpoint", [None, "/v1/messages"])
@respx.mock
def test_discovery_empty_base_keeps_exact_error_without_request(endpoint):
    response = fetch_models_sync(ModelFetchRequest(
        token=81, app_id="ai-grammar", api_base="", api_key="literal", endpoint=endpoint,
    ))
    assert response.model_dump() == {
        "token": 81, "success": False, "models": [],
        "error_message": "API Base URL cannot be empty.", "endpoint_used": None,
    }
    assert not respx.calls
