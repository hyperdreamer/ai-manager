import copy
from dataclasses import replace
import hashlib
import pytest
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.blast_radius import auth_mismatch_warning, endpoint, find_affected_dependents, normalize_loopback_url, urls_match
from ai_manager.config.config_errors import ConfigLoadError
from ai_manager.config.models import AppAIConfig
from ai_manager.config.structured_config import load
from ai_manager.config.structured_models import Mutation
from ai_manager.config.yaml_manager import render_app_config

BASE = "http://127.0.0.1:8000"


@pytest.mark.parametrize("url,match", [(BASE, True), (BASE + "/", True), ("http://localhost:8000", True), ("http://[::1]:8000", True), ("http://LOCALHOST:8000", True), (BASE + "/v1", False), ("http://127.0.0.1:8001", False), ("https://127.0.0.1:8000", False), (BASE + "/?x=1", False), ("http://0.0.0.0:8000", False), (BASE + "///", False), ("http://user:pw@127.0.0.1:8000", False)])
def test_normative_url_matrix(url, match):
    assert urls_match(BASE, url) is match
    assert urls_match(url, BASE) is match


def test_normalization_changes_host_only():
    assert normalize_loopback_url("HTTP://u:p@LOCALHOST:08000/v1/?x=1#f") == "HTTP://u:p@127.0.0.1:08000/v1/?x=1#f"
    assert not urls_match("HTTP://localhost:8000", BASE)
    assert normalize_loopback_url("http://127.0.0.2:8000") is None
    assert normalize_loopback_url("not a URL") is None


def drafts(workspace):
    apps = get_managed_apps(workspace)
    before = load("chat2api", apps["chat2api"].relative_path / "config.json")
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    return apps, before, after


def test_match_carries_exact_new_url_without_host_normalization(five_app_workspace):
    apps, before, after = drafts(five_app_workspace)
    path = apps["textkit"].relative_path / "config.yaml"
    path.write_bytes(path.read_bytes().replace(BASE.encode(), b"http://localhost:8000"))
    matches = find_affected_dependents(apps, before, after)
    assert [m.meta.id for m in matches] == ["ai-grammar", "textkit", "yt2txt"]
    textkit = matches[1]
    assert textkit.old_api_base == "http://localhost:8000"
    rendered = render_app_config(textkit.meta, textkit.doc, lambda tree: tree["ai"].__setitem__("api_base", textkit.new_api_base))
    assert b'api_base: "http://127.0.0.1:8123"' in rendered
    assert b"localhost" not in rendered


def test_ipv6_listener_yields_bracketed_new_url(five_app_workspace):
    apps, before, _after = drafts(five_app_workspace)
    after = replace(before, mutations=(Mutation(("server", "host"), "set", "::1"),))
    matches = find_affected_dependents(apps, before, after)
    assert [m.meta.id for m in matches] == ["ai-grammar", "textkit", "yt2txt"]
    assert {m.new_api_base for m in matches} == {"http://[::1]:8000"}


def test_three_snapshots_and_only_exact_api_base_changes(five_app_workspace, monkeypatch):
    apps, before, after = drafts(five_app_workspace)
    monkeypatch.setattr("ai_manager.config.yaml_manager.write_app_config", lambda *a, **k: pytest.fail("D7 cannot call a writer"))
    matches = find_affected_dependents(apps, before, after)
    assert [m.meta.id for m in matches] == ["ai-grammar", "textkit", "yt2txt"]
    for match in matches:
        assert match.raw_bytes == match.path.read_bytes()
        assert match.raw_sha256 == hashlib.sha256(match.raw_bytes).digest()
        original = copy.deepcopy(match.doc)
        def update(tree):
            tree["ai"]["api_base"] = match.new_api_base
        rendered = render_app_config(match.meta, match.doc, update)
        assert rendered == match.raw_bytes.replace(b"http://127.0.0.1:8000", b"http://127.0.0.1:8123")
        assert match.doc == original and match.path.read_bytes() == match.raw_bytes
        assert match.saved_config.api_base == BASE
    assert matches[1].saved_config.is_split_model
    assert endpoint(replace(before, mutations=(Mutation(("server", "host"), "set", "::1"),)))[2] == "http://[::1]:8000"


def test_unchanged_listener_reads_nothing_and_external_base_excluded(five_app_workspace, monkeypatch):
    apps, before, after = drafts(five_app_workspace)
    with monkeypatch.context() as patch:
        patch.setattr("ai_manager.config.blast_radius._snapshot", lambda path: pytest.fail("auth-only edit must not inspect disk"))
        assert find_affected_dependents(apps, before, replace(before, mutations=(Mutation(("server", "auth_token_env"), "set", "OTHER_TOKEN"),))) == ()
    path = apps["textkit"].relative_path / "config.yaml"
    path.write_bytes(path.read_bytes().replace(BASE.encode(), b"https://api.example.invalid"))
    assert [m.meta.id for m in find_affected_dependents(apps, before, after)] == ["ai-grammar", "yt2txt"]


@pytest.mark.parametrize("failure", ["missing", "anchor", "readonly", "malformed", "symlink"])
def test_uninspectable_dependent_refuses_without_example_creation(five_app_workspace, failure):
    apps, before, after = drafts(five_app_workspace)
    path = apps["textkit"].relative_path / "config.yaml"
    if failure == "missing":
        path.unlink()
    elif failure == "anchor":
        path.write_text("ai: &a {api_base: 'http://127.0.0.1:8000'}\nother: *a\n")
    elif failure == "readonly":
        path.chmod(0o444)
    elif failure == "malformed":
        path.write_text("ai: [broken\n")
    else:
        path.unlink()
        path.symlink_to("config.example.yaml")
    with pytest.raises(ConfigLoadError, match="Cannot inspect dependent configuration"):
        find_affected_dependents(apps, before, after)
    if failure == "missing":
        assert not path.exists()


@pytest.mark.parametrize("key,auth,warn", [("$OTHER_TOKEN", "CHAT2API_TOKEN", True), (" $OTHER_TOKEN ", "CHAT2API_TOKEN", True), ("$CHAT2API_TOKEN", "CHAT2API_TOKEN", False), ("literal", "CHAT2API_TOKEN", False), ("", "CHAT2API_TOKEN", False), ("$OTHER_TOKEN", None, False)])
def test_auth_warnings(key, auth, warn):
    message = auth_mismatch_warning(AppAIConfig(api_key=key), auth)
    assert (message is not None) is warn
    if warn:
        assert message.format(app_id="ai-grammar") == "ai-grammar uses $OTHER_TOKEN, but chat2api auth_token_env is 'CHAT2API_TOKEN'; requests may fail with HTTP 401."
