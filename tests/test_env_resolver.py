import os
import pytest
from ai_manager.utils.env_resolver import (
    get_env_var_status,
    is_env_var_reference,
    resolve_api_key,
)


def test_is_env_var_reference():
    assert is_env_var_reference("$OPENAI_API_KEY") is True
    assert is_env_var_reference("$MY_KEY_123") is True
    assert is_env_var_reference("sk-123456") is False
    assert is_env_var_reference("") is False
    assert is_env_var_reference("$") is False


def test_resolve_api_key(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret-value-abc")
    assert resolve_api_key("$TEST_KEY") == "secret-value-abc"
    assert resolve_api_key("plaintext-key") == "plaintext-key"
    assert resolve_api_key("$UNSET_KEY") == ""
    assert resolve_api_key("") == ""


def test_get_env_var_status(monkeypatch):
    monkeypatch.setenv("EXISTS", "12345")
    is_set, msg = get_env_var_status("$EXISTS")
    assert is_set is True
    assert "✓" in msg

    is_set_unset, msg_unset = get_env_var_status("$NOT_SET")
    assert is_set_unset is False
    assert "⚠️" in msg_unset

    is_plain, msg_plain = get_env_var_status("regular-key")
    assert is_plain is True
    assert "Plaintext" in msg_plain
