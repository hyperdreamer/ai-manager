from types import SimpleNamespace
import pytest
from ai_manager.config.protocols import (
    ENDPOINT_VALUES, PROTOCOLS, is_valid_endpoint, compose_request_url,
    base_conflicts_with_endpoint, effective_api_base,
)

VALUES = ("/v1/chat/completions", "/v1/responses", "/v1/messages")


def test_explicit_vocabulary_is_exact():
    assert tuple(p.value for p in PROTOCOLS) == VALUES
    assert ENDPOINT_VALUES == frozenset(VALUES)
    for value in VALUES:
        assert is_valid_endpoint(value)
    for value in (None, "", " /v1/messages", "/v1/messages ", "messages",
                  "/v1/completions", "/v1/other", "https://x/v1/messages",
                  True, 42, [], {}, set()):
        assert not is_valid_endpoint(value), repr(value)


@pytest.mark.parametrize("app,base,want", [
    ("ai-grammar", "https://x", "https://x/v1/chat/completions"),
    ("ai-grammar", "https://x/v1", "https://x/v1/chat/completions"),
    ("ai-grammar", "https://x/v1/", "https://x/v1//chat/completions"),
    ("textkit", "https://x", "https://x/v1/chat/completions"),
    ("textkit", "https://x/v1", "https://x/v1/v1/chat/completions"),
    ("textkit", "https://x/v1/", "https://x/v1/v1/chat/completions"),
])
def test_request_url_exact_legacy_matrix(app, base, want):
    assert compose_request_url(app, base, None) == want


@pytest.mark.parametrize("app", ["ai-grammar", "textkit"])
@pytest.mark.parametrize("endpoint", VALUES)
@pytest.mark.parametrize("base", ["https://x", "https://x/", "https://x/gateway/",
                                  "https://x/v1", "https://x/v1/"])
def test_explicit_request_url_preserves_gateway_prefix(app, endpoint, base):
    assert compose_request_url(app, " " + base + " ", endpoint) == base.rstrip("/") + endpoint


def test_base_conflict_is_path_only_and_total():
    for base in ("https://x/v1", "https://x/v1/", "https://x/gateway/v1///"):
        assert base_conflicts_with_endpoint(base, "/v1/messages")
        assert not base_conflicts_with_endpoint(base, None)
    for base in ("https://v1.example.com", "https://x?x=/v1", "https://x#/v1",
                 "https://x/v10", "https://x/V1", "https://[", "https://[::1"):
        assert not base_conflicts_with_endpoint(base, "/v1/messages")
    assert base_conflicts_with_endpoint("https://[::1]/v1", "/v1/messages")


@pytest.mark.parametrize("app", ["ai-grammar", "textkit"])
def test_omitted_base_uses_mode_specific_target_default(app):
    loaded = SimpleNamespace(api_base="http://127.0.0.1:3000")
    snap = SimpleNamespace(config=loaded, api_base_present=False)
    draft = SimpleNamespace(api_base=loaded.api_base, endpoint=None)
    want = "https://api.openai.com/v1" if app == "ai-grammar" else "https://api.openai.com"
    assert effective_api_base(app, draft, snap) == want
    draft.endpoint = "/v1/messages"
    assert effective_api_base(app, draft, snap) == "https://api.openai.com"
    draft.api_base = "https://pending/gateway"
    assert effective_api_base(app, draft, snap) == draft.api_base
    draft.api_base = loaded.api_base
    assert effective_api_base(app, draft, snap) == "https://api.openai.com"
    snap.api_base_present = True
    assert effective_api_base(app, draft, snap) == loaded.api_base
