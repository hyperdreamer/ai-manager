import builtins
import copy
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import stat
import threading
import pytest
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.blast_radius import auth_mismatch_warning, endpoint, find_affected_dependents, normalize_loopback_url, urls_match
from ai_manager.config.config_errors import ConfigLoadError
from ai_manager.config.models import AppAIConfig
from ai_manager.config.structured_config import load
from ai_manager.config.structured_models import Mutation
from ai_manager.config.transaction import Transaction
from ai_manager.config.yaml_manager import render_app_config

BASE = "http://127.0.0.1:8000"
# A regression that opens the non-regular leaf blocks forever; bound it so pytest fails
# instead of hanging the suite.
FIFO_TIMEOUT_SECONDS = 10.0


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


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="platform provides no os.mkfifo")
def test_non_regular_dependent_is_refused_without_read_or_mutation(five_app_workspace, monkeypatch):
    apps, before, after = drafts(five_app_workspace)
    path = apps["textkit"].relative_path / "config.yaml"
    path.unlink()
    os.mkfifo(path)
    fifo = os.lstat(path)
    assert stat.S_ISFIFO(fifo.st_mode)

    reads: list[tuple[str, Path]] = []
    original_read_bytes = Path.read_bytes
    original_open = builtins.open

    def spy_read_bytes(self, *args, **kwargs):
        if os.path.abspath(self) == os.path.abspath(path):
            reads.append(("read_bytes", Path(self)))
        return original_read_bytes(self, *args, **kwargs)

    def spy_open(file, *args, **kwargs):
        try:
            target = Path(os.fspath(file)) if isinstance(file, (str, bytes, os.PathLike)) else None
        except TypeError:
            target = None
        if target is not None and os.path.abspath(target) == os.path.abspath(path):
            reads.append(("open", target))
        return original_open(file, *args, **kwargs)

    mutations: list[str] = []

    def record_phase(name):
        def phase(self, *args, **kwargs):
            mutations.append(name)
            return None
        return phase

    outcome: list[BaseException] = []

    def inspect() -> None:
        try:
            find_affected_dependents(apps, before, after)
        except BaseException as exc:  # noqa: BLE001 - recorded, re-asserted below
            outcome.append(exc)

    # Scope the spies to the inspection itself, so they are already removed when the
    # assertions below format messages (a blocked worker must not break reporting) and the
    # autouse isolation fixture's patches are left untouched.
    with monkeypatch.context() as patch:
        for name in ("prepare", "backups", "stage", "replace_all", "rollback"):
            patch.setattr(Transaction, name, record_phase(name))
        patch.setattr(Path, "read_bytes", spy_read_bytes)
        patch.setattr(builtins, "open", spy_open)
        worker = threading.Thread(target=inspect, name="dependent-inspection", daemon=True)
        worker.start()
        worker.join(timeout=FIFO_TIMEOUT_SECONDS)
        timed_out = worker.is_alive()

    assert reads == [], f"inspection attempted to read the non-regular leaf: {reads!r}"
    assert mutations == [], f"inspection reached a mutation phase: {mutations!r}"
    assert not timed_out, "dependent inspection blocked on a non-regular configuration leaf"
    assert len(outcome) == 1 and isinstance(outcome[0], ConfigLoadError), outcome
    assert "Cannot inspect dependent configuration" in str(outcome[0])
    # Pins the non-regular rejection specifically, so treating a FIFO as a missing file
    # (which would raise the same wrapper) cannot satisfy this test.
    assert "must be a regular file" in str(outcome[0])
    assert outcome[0].__cause__ is not None
    assert os.path.abspath(outcome[0].path) == os.path.abspath(path)

    current = os.lstat(path)
    assert stat.S_ISFIFO(current.st_mode)
    assert (current.st_ino, current.st_mtime_ns, current.st_size) == (fifo.st_ino, fifo.st_mtime_ns, fifo.st_size)
    assert sorted(item.name for item in path.parent.iterdir()) == ["config.example.yaml", "config.yaml"]


# --- Task 9: selected dependents commit through one transaction -----------


@pytest.mark.parametrize("selected", [(), ("textkit",), ("ai-grammar", "textkit", "yt2txt")])
def test_commit_selected_members_only(five_app_workspace, monkeypatch, selected):
    from ai_manager.config import structured_config as sc
    from ai_manager.config.structured_models import ValidationResult
    import ai_manager.services.service_validation as service
    monkeypatch.setattr(service, "validate_candidate", lambda *a: ValidationResult("service", "fixture valid"))
    apps, before, after = drafts(five_app_workspace)
    matches = find_affected_dependents(apps, before, after)
    originals = {m.meta.id: m.raw_bytes for m in matches}
    result = sc.commit("chat2api", before.path, after, before.raw_sha256, dependents=tuple(m for m in matches if m.meta.id in selected))
    assert len(result.transaction.files) == 1 + len(selected)
    assert set(result.saved_dependents) == set(selected)
    for match in matches:
        actual = match.path.read_bytes()
        expected = originals[match.meta.id].replace(b":8000", b":8123") if match.meta.id in selected else originals[match.meta.id]
        assert actual == expected
    assert result.document.doc["server"]["port"] == 8123


def test_dialog_snapshot_stale_refuses_every_member(five_app_workspace, monkeypatch):
    from ai_manager.config import structured_config as sc
    from ai_manager.config.config_errors import StaleDocumentError
    from ai_manager.config.structured_models import ValidationResult
    import ai_manager.services.service_validation as service
    monkeypatch.setattr(service, "validate_candidate", lambda *a: ValidationResult("service", "fixture valid"))
    apps, before, after = drafts(five_app_workspace)
    matches = find_affected_dependents(apps, before, after)
    matches[1].path.write_bytes(matches[1].raw_bytes + b"# later hand edit\n")
    snapshots = {m.path: m.path.read_bytes() for m in matches}
    with pytest.raises(StaleDocumentError):
        sc.commit("chat2api", before.path, after, before.raw_sha256, dependents=matches)
    assert before.path.read_bytes() == before.raw_bytes
    assert all(path.read_bytes() == raw for path, raw in snapshots.items())


def test_dependent_bytes_are_sealed_before_stage_three(five_app_workspace, monkeypatch):
    from ai_manager.config import structured_config as sc
    from ai_manager.config.structured_models import ValidationResult
    from ai_manager.config.transaction import Transaction
    import ai_manager.services.service_validation as service

    path = five_app_workspace / "chat2api/config.json"
    before = sc.load("chat2api", path)
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    apps = get_managed_apps(five_app_workspace)
    matches = find_affected_dependents(apps, before, after)
    expected = {
        match.path: render_app_config(match.meta, match.doc, lambda tree, m=match: tree["ai"].__setitem__("api_base", m.new_api_base))
        for match in matches
    }
    staged: list[dict[Path, bytes]] = []

    def validator(kind, target, app_dir, raw):
        # A later mutable source change after sealing must not reach the target.
        for match in matches:
            match.doc["ai"]["api_base"] = "http://127.0.0.1:9999"
        return ValidationResult("service", "fixture valid")

    monkeypatch.setattr(service, "validate_candidate", validator)
    original = Transaction.stage
    def stage(self, rendered):
        staged.append({p: b for p, b in rendered.items() if p != path.resolve()})
        return original(self, rendered)
    monkeypatch.setattr(Transaction, "stage", stage)
    result = sc.commit("chat2api", path, after, before.raw_sha256, dependents=matches)
    assert staged == [expected]
    for match in matches:
        assert match.path.read_bytes() == match.raw_bytes.replace(b":8000", b":8123")
        assert b"9999" not in match.path.read_bytes()
    assert set(result.saved_dependents) == {"ai-grammar", "textkit", "yt2txt"}


# --- Task 3: dependent reads pass metadata, not shape-inferred ownership ----


def _write_dependent(path: Path, endpoint_line: str = "") -> None:
    path.write_text(
        "ai:\n"
        '  api_base: "http://127.0.0.1:8000"\n'
        '  api_key: "$CHAT2API_TOKEN"\n'
        '  model: "dependent-model"\n' + endpoint_line,
        encoding="utf-8",
    )


def test_dependent_inspection_normalizes_endpoint_with_metadata(five_app_workspace):
    apps, before, after = drafts(five_app_workspace)
    _write_dependent(apps["ai-grammar"].relative_path / "config.yaml", "  endpoint: /v1/messages\n")
    _write_dependent(apps["textkit"].relative_path / "config.yaml", "  endpoint: /v1/completions\n")
    _write_dependent(apps["yt2txt"].relative_path / "config.yaml", "  endpoint: /v1/messages\n")
    matches = find_affected_dependents(apps, before, after)
    assert [m.meta.id for m in matches] == ["ai-grammar", "textkit", "yt2txt"]
    grammar, text, youtube = (m.saved_config for m in matches)
    assert (grammar.endpoint, grammar.endpoint_raw) == ("/v1/messages", None)
    assert (text.endpoint, text.endpoint_raw) == (None, "'/v1/completions'")
    assert (youtube.endpoint, youtube.endpoint_raw) == (None, None)


def test_dependent_commit_normalizes_with_dependent_metadata(five_app_workspace, monkeypatch):
    from ai_manager.config import structured_config as sc
    from ai_manager.config.structured_models import ValidationResult
    import ai_manager.services.service_validation as service

    monkeypatch.setattr(service, "validate_candidate", lambda *a: ValidationResult("service", "fixture valid"))
    apps, before, after = drafts(five_app_workspace)
    grammar_path = apps["ai-grammar"].relative_path / "config.yaml"
    youtube_path = apps["yt2txt"].relative_path / "config.yaml"
    _write_dependent(grammar_path, "  endpoint: /v1/messages\n")
    _write_dependent(youtube_path, "  endpoint: /hand-written/value\n")
    matches = find_affected_dependents(apps, before, after)
    result = sc.commit("chat2api", before.path, after, before.raw_sha256, dependents=matches)
    assert result.saved_dependents["ai-grammar"].endpoint == "/v1/messages"
    assert (result.saved_dependents["yt2txt"].endpoint, result.saved_dependents["yt2txt"].endpoint_raw) == (None, None)
    assert b"  endpoint: /v1/messages\n" in grammar_path.read_bytes()
    assert b"  endpoint: /hand-written/value\n" in youtube_path.read_bytes()
