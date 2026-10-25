import hashlib
import os
import shutil
import stat
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock
import pytest
from ai_manager.config import yaml_manager
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.config_errors import (
    CommittedWriteError,
    ConfigError,
    ConfigLoadError,
    ConfigShapeError,
    StaleDocumentError,
    TransactionError,
)
from ai_manager.config.yaml_manager import (
    _apply_ai_config,
    _config_from_document,
    _get_yaml_engine,
    read_app_config,
    read_app_config_snapshot,
    render_app_config,
    write_app_config,
)
from ai_manager.config.models import AppAIConfig, AppMetadata
from ai_manager.config.transaction import Transaction
from tests.endpoint_helpers import meta_for


@pytest.fixture
def temp_workspace(tmp_path):
    fixtures_dir = Path(__file__).parent / "fixtures"
    ai_grammar_dir = tmp_path / "ai-grammar" / "backend"
    textkit_dir = tmp_path / "textkit" / "backend"
    yt2txt_dir = tmp_path / "yt2txt" / "backend"

    ai_grammar_dir.mkdir(parents=True)
    textkit_dir.mkdir(parents=True)
    yt2txt_dir.mkdir(parents=True)

    shutil.copy2(fixtures_dir / "ai_grammar_config.yaml", ai_grammar_dir / "config.yaml")
    shutil.copy2(fixtures_dir / "textkit_unified_config.yaml", textkit_dir / "config.yaml")
    shutil.copy2(fixtures_dir / "yt2txt_config.yaml", yt2txt_dir / "config.yaml")

    return tmp_path


def test_read_app_config(temp_workspace):
    meta_grammar = AppMetadata(
        id="ai-grammar",
        display_name="ai-grammar",
        relative_path=temp_workspace / "ai-grammar" / "backend",
        default_port=8766,
    )
    cfg = read_app_config(meta_grammar)
    assert cfg.api_base == "http://192.168.191.3:3000"
    assert cfg.model == "gemini-flash-high"
    assert not cfg.is_split_model

    meta_yt2txt = AppMetadata(
        id="yt2txt",
        display_name="yt2txt",
        relative_path=temp_workspace / "yt2txt" / "backend",
        default_port=8666,
    )
    cfg_yt = read_app_config(meta_yt2txt)
    assert cfg_yt.api_key == "$OPENAI_API_KEY"
    assert cfg_yt.model == "gpt-4o-transcribe"


def test_write_app_config_preserves_comments(temp_workspace):
    meta_grammar = AppMetadata(
        id="ai-grammar",
        display_name="ai-grammar",
        relative_path=temp_workspace / "ai-grammar" / "backend",
        default_port=8766,
    )
    saved = read_app_config_snapshot(meta_grammar)
    new_cfg = AppAIConfig(
        api_base="https://tokenhub.tencentmaas.com",
        api_key="sk-new-token",
        model="deepseek-v3",
    )
    write_app_config(meta_grammar, new_cfg, baseline=saved.config, expected_sha256=saved.sha256)

    # Re-read
    cfg = read_app_config(meta_grammar)
    assert cfg.api_base == "https://tokenhub.tencentmaas.com"
    assert cfg.model == "deepseek-v3"

    # Verify backup exists
    assert len(list((temp_workspace / "ai-grammar" / "backend").glob("config.yaml.*.bak"))) == 1

    # Read raw content to check comment preservation
    raw = (temp_workspace / "ai-grammar" / "backend" / "config.yaml").read_text(encoding="utf-8")
    assert "# Enable detailed debug logging to stderr" in raw
    assert "#model: gpt-5.6-terra" in raw


def test_textkit_split_model_transitions(temp_workspace):
    meta_textkit = AppMetadata(
        id="textkit",
        display_name="textkit",
        relative_path=temp_workspace / "textkit" / "backend",
        default_port=8765,
        supports_split_models=True,
    )

    # 1. Switch unified to split
    saved = read_app_config_snapshot(meta_textkit)
    split_cfg = AppAIConfig(
        api_base="http://localhost:3000",
        api_key="sk-test",
        is_split_model=True,
        ocr_model="qwen-ocr",
        text_model="deepseek-chat",
    )
    write_app_config(meta_textkit, split_cfg, baseline=saved.config, expected_sha256=saved.sha256)

    read_split = read_app_config(meta_textkit)
    assert read_split.is_split_model is True
    assert read_split.ocr_model == "qwen-ocr"
    assert read_split.text_model == "deepseek-chat"

    # 2. Switch split back to unified
    saved = read_app_config_snapshot(meta_textkit)
    unified_cfg = AppAIConfig(
        api_base="http://localhost:3000",
        api_key="sk-test",
        is_split_model=False,
        model="claude-3-5-sonnet",
    )
    write_app_config(meta_textkit, unified_cfg, baseline=saved.config, expected_sha256=saved.sha256)

    read_unified = read_app_config(meta_textkit)
    assert read_unified.is_split_model is False
    assert read_unified.model == "claude-3-5-sonnet"


def test_render_is_pure_and_shares_the_writer_rendering_step(five_app_workspace, monkeypatch):
    meta = get_managed_apps(five_app_workspace)["textkit"]
    path = meta.relative_path / "config.yaml"
    original = path.read_bytes()
    before_listing = sorted(p.name for p in meta.relative_path.iterdir())
    doc = _get_yaml_engine().load(original.decode())
    calls = []
    real_render = yaml_manager._render_document

    def spy(tree):
        calls.append(tree)
        return real_render(tree)

    render_app_config(meta, doc, lambda tree: tree["ai"].__setitem__("api_base", "http://127.0.0.1:8123"))
    assert sorted(p.name for p in meta.relative_path.iterdir()) == before_listing
    assert not list(meta.relative_path.glob("*.bak"))
    assert not list(meta.relative_path.glob("*.tmp*"))

    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "text_model": "rendered"})
    monkeypatch.setattr(yaml_manager, "_render_document", spy)
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert len(calls) == 1


def test_render_refuses_non_llm_metadata(five_app_workspace):
    apps = get_managed_apps(five_app_workspace)
    chat = apps["chat2api"]
    with pytest.raises(ConfigError):
        render_app_config(chat, {}, lambda tree: None)


def test_checked_writer_preserves_mode_and_comments(five_app_workspace):
    meta = get_managed_apps(five_app_workspace)["ai-grammar"]
    path = meta.relative_path / "config.yaml"
    original = path.read_bytes()
    os.chmod(path, 0o640)
    digest = hashlib.sha256(original).digest()
    saved = read_app_config_snapshot(meta)
    cfg = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "mode-preserved"})
    write_app_config(meta, cfg, baseline=saved.config, expected_sha256=digest)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    raw = path.read_bytes()
    assert b"# bridge endpoint" in raw and b"# Keep debug and commented choices" in raw
    assert not (path.parent / "config.yaml.bak").exists()


def test_pure_renderer_and_checked_writer(five_app_workspace, monkeypatch):
    meta = get_managed_apps(five_app_workspace)["ai-grammar"]
    path = meta.relative_path / "config.yaml"
    original = path.read_bytes()
    doc = _get_yaml_engine().load(original.decode())
    def update(tree):
        tree["ai"]["api_base"] = "http://127.0.0.1:8123"
    rendered = render_app_config(meta, doc, update)
    assert rendered == original.replace(b":8000", b":8123")
    assert path.read_bytes() == original and doc["ai"]["api_base"].endswith(":8000")
    saved = read_app_config_snapshot(meta)
    cfg = saved.config.model_copy(update={"model": "checked"})
    digest = hashlib.sha256(original).digest()
    path.write_bytes(original + b"# hand edit\n")
    with pytest.raises(StaleDocumentError):
        write_app_config(meta, cfg, baseline=saved.config, expected_sha256=digest)
    assert path.read_bytes() == original + b"# hand edit\n"
    path.unlink()
    with pytest.raises(StaleDocumentError):
        write_app_config(meta, cfg, baseline=saved.config, expected_sha256=digest)
    assert not path.exists()
    path.write_bytes(original)
    installed = write_app_config(meta, cfg, baseline=saved.config, expected_sha256=digest)
    assert installed == hashlib.sha256(path.read_bytes()).digest()
    assert read_app_config(meta).model == "checked"
    assert list(path.parent.glob("config.yaml.*.bak")) and not (path.parent / "config.yaml.bak").exists()
    baseline = read_app_config(meta)
    legacy = baseline.model_copy(update={"model": "legacy"})
    installed = write_app_config(meta, legacy, baseline=baseline)
    assert installed == hashlib.sha256(path.read_bytes()).digest()
    assert (path.parent / "config.yaml.bak").exists()


# --- Task 3: metadata-aware, non-creating snapshot reads ------------------


@pytest.mark.parametrize("app", ["ai-grammar", "textkit", "yt2txt"])
@pytest.mark.parametrize("line,value,raw", [
    ("", None, None),
    ("  endpoint: /v1/chat/completions\n", "/v1/chat/completions", None),
    ("  endpoint: /v1/responses\n", "/v1/responses", None),
    ("  endpoint: /v1/messages\n", "/v1/messages", None),
    ("  endpoint: null\n", None, "None"),
    ("  endpoint: ''\n", None, "''"),
    ("  endpoint: /v1/completions\n", None, "'/v1/completions'"),
    ("  endpoint: 42\n", None, "42"),
    ("  endpoint: true\n", None, "True"),
])
def test_endpoint_read_matrix_with_metadata(tmp_path, app, line, value, raw):
    meta = meta_for(tmp_path, app, selectable=app != "yt2txt")
    (meta.relative_path / "config.yaml").write_text("ai:\n  model: m\n" + line)
    config = read_app_config_snapshot(meta).config
    assert (config.endpoint, config.endpoint_raw) == (
        (value, raw) if app != "yt2txt" else (None, None)
    )


@pytest.mark.parametrize("base_line,present", [
    (b"", False),
    (b"  api_base: http://127.0.0.1:3000\n", True),
    (b"  api_base: null\n", True),
])
def test_snapshot_hashes_the_same_bytes_it_parses(tmp_path, monkeypatch, base_line, present):
    import ai_manager.config.structured_config as sc

    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    raw = b"# spelling matters\nai:\n" + base_line + b"  model: exact\n"
    path.write_bytes(raw)
    actual = sc._snapshot
    calls = []

    def once(p):
        calls.append(p)
        result = actual(p)
        path.write_bytes(b"ai: {model: different}\n")
        return result

    monkeypatch.setattr(sc, "_snapshot", once)
    snap = read_app_config_snapshot(meta)
    assert snap.config.model == "exact" and snap.sha256 == sha256(raw).digest()
    assert snap.api_base_present is present and len(calls) == 1


@pytest.mark.parametrize("raw", [
    b"[\n",
    b"ai: {model: a, model: b}\n",
    b"[]\n",
    b"null\n",
    b"false\n",
    b"0\n",
    b"ai: []\n",
    b"ai: false\n",
    b"\xff",
])
def test_load_failures_never_become_successful_default_snapshot(tmp_path, raw):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    path.write_bytes(raw)
    with pytest.raises(ConfigLoadError) as error:
        read_app_config_snapshot(meta)
    assert error.value.path == path
    assert path.read_bytes() == raw


def test_snapshot_read_is_noncreating_and_regular_file_only(tmp_path):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    (path.parent / "config.example.yaml").write_text("ai: {model: example}\n")
    with pytest.raises(ConfigLoadError, match="Configuration file is missing"):
        read_app_config_snapshot(meta)
    assert not path.exists()
    path.symlink_to(path.parent / "config.example.yaml")
    with pytest.raises(ConfigLoadError):
        read_app_config_snapshot(meta)
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(ConfigLoadError):
        read_app_config_snapshot(meta)
    path.unlink()
    for raw in (b"", b"# comments only\n", b"ai: null\n"):
        path.write_bytes(raw)
        path.chmod(0o444)
        assert read_app_config_snapshot(meta).sha256 == sha256(raw).digest()
        path.chmod(0o600)


@pytest.mark.parametrize("raw,message,reason", [
    (b"[]\n", "Configuration root must be a mapping; save is disabled.", "non-dict-root"),
    (b"null\n", "Configuration root must be a mapping; save is disabled.", "non-dict-root"),
    (b"false\n", "Configuration root must be a mapping; save is disabled.", "non-dict-root"),
    (b"ai: []\n", "AI must be a mapping when present; save is disabled.", "load-error"),
    (b"ai: false\n", "AI must be a mapping when present; save is disabled.", "load-error"),
])
def test_shape_errors_use_exact_messages_and_reasons(tmp_path, raw, message, reason):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    path.write_bytes(raw)
    with pytest.raises(ConfigShapeError) as error:
        read_app_config_snapshot(meta)
    assert error.value.detail == message
    assert error.value.reason == reason
    assert error.value.path == path


def test_direct_helper_shape_errors_and_empty_mapping(tmp_path):
    meta = meta_for(tmp_path)
    with pytest.raises(ValueError, match=r"^Configuration root must be a mapping; save is disabled\.$"):
        _config_from_document([], meta)
    with pytest.raises(ValueError, match=r"^AI must be a mapping when present; save is disabled\.$"):
        _config_from_document({"ai": []}, meta)
    assert _config_from_document({}, meta) == AppAIConfig()


def test_reader_split_classification_uses_metadata(tmp_path):
    tree = {"ai": {"model": "inactive", "ocr": {"api_key_env": "VISION_KEY"}}}
    grammar = _config_from_document(tree, meta_for(tmp_path))
    text = _config_from_document(tree, meta_for(tmp_path, "textkit"))
    assert not grammar.is_split_model and grammar.model == "inactive"
    assert text.is_split_model and text.model is None and text.ocr_model is None


def test_render_remains_pure(tmp_path):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    original = b"ai:\n  model: 'old' # keep\n"
    path.write_bytes(original)
    tree = _get_yaml_engine().load(original.decode())
    seen = []

    def mutate(candidate):
        seen.append(candidate)
        candidate["ai"]["model"] = "new"

    rendered = render_app_config(meta, tree, mutate)
    assert len(seen) == 1 and seen[0] is not tree
    assert tree["ai"]["model"] == "old" and path.read_bytes() == original
    assert b"'new' # keep" in rendered


def test_compatibility_reader_creates_from_example_then_returns_owned_copy(tmp_path):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    (path.parent / "config.example.yaml").write_text(
        "ai:\n  api_base: http://127.0.0.1:9100\n  model: 'example'\n"
    )
    first = read_app_config(meta)
    assert path.exists() and first.api_base == "http://127.0.0.1:9100"
    first.model = "mutated"
    assert read_app_config(meta).model == "example"
    assert yaml_manager.read_app_config(meta).model == "example"


# --- Task 4: diff-only writes and the transaction commit boundary ---------

PROVIDER_ONLY = (
    b'ai:\n  api_base: "https://gateway.example.test"\n'
    b'  api_key: "$EXAMPLE_API_KEY"\n  model: "non-default-base-model"\n'
    b'  messages_default_max_tokens: 6000\n  temperature: 0.2\n'
    b'  endpoints:\n    check: 0.1\n  ocr:\n    api_base: "https://vision.example.test"\n'
    b'    api_key_env: "VISION_KEY"\n  text:\n    api_key_env: "TEXT_KEY"\n'
)


def test_protocol_only_save_preserves_provider_only_mappings_and_base_model(tmp_path):
    meta = meta_for(tmp_path, "textkit")
    path = meta.relative_path / "config.yaml"
    path.write_bytes(PROVIDER_ONLY)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "endpoint": "/v1/messages"})
    installed = write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == PROVIDER_ONLY + b"  endpoint: /v1/messages\n"
    assert installed == hashlib.sha256(path.read_bytes()).digest()


@pytest.mark.parametrize("spelling", [b'"/v1/completions"', b"null", b"''", b"42", b"true"])
def test_invalid_to_auto_removes_exact_key_bytes(tmp_path, spelling):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    before = b'ai:\n  api_base: "https://gateway.example.test"\n  endpoint: ' + spelling + b'\n  model: "model-a"\n'
    path.write_bytes(before)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "endpoint_raw": None})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == b'ai:\n  api_base: "https://gateway.example.test"\n  model: "model-a"\n'


@pytest.mark.parametrize("checked", [True, False])
def test_noop_writer_has_no_backup_or_replace(tmp_path, monkeypatch, checked):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    raw = b"# odd formatting\nai: {model: 'm'}\n"
    path.write_bytes(raw)
    path.chmod(0o444)
    saved = read_app_config_snapshot(meta)
    forbidden = Mock(side_effect=AssertionError("no-op attempted a write"))
    monkeypatch.setattr(yaml_manager, "render_app_config", forbidden)
    monkeypatch.setattr(yaml_manager.os, "replace", forbidden)
    monkeypatch.setattr(yaml_manager.shutil, "copy2", forbidden)
    monkeypatch.setattr(Transaction, "__enter__", forbidden)
    result = write_app_config(meta, saved.config, baseline=saved.config,
                              expected_sha256=saved.sha256 if checked else None)
    assert result == hashlib.sha256(raw).digest() and path.read_bytes() == raw
    assert stat.S_IMODE(path.stat().st_mode) == 0o444
    assert not list(path.parent.glob("*.bak")) and not list(path.parent.glob("*.tmp*"))
    assert not list(path.parent.glob(".*.tmp")) and not list(path.parent.glob("*.lock"))


@pytest.mark.parametrize("no_op", [False, True])
def test_checked_writer_stale_refuses_before_render(tmp_path, monkeypatch, no_op):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    path.write_bytes(b"ai: {model: old}\n")
    path.chmod(0o640)
    saved = read_app_config_snapshot(meta)
    external = b"ai: {model: old, endpoint: /v1/messages}\n"
    path.write_bytes(external)
    forbidden = Mock(side_effect=AssertionError("render before stale"))
    monkeypatch.setattr(yaml_manager, "render_app_config", forbidden)
    monkeypatch.setattr(Transaction, "backups", forbidden)
    monkeypatch.setattr(yaml_manager.os, "replace", forbidden)
    draft = saved.config if no_op else AppAIConfig(model="pending")
    with pytest.raises(StaleDocumentError) as caught:
        write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert caught.value.expected_sha256 == saved.sha256
    assert caught.value.actual_sha256 == hashlib.sha256(external).digest()
    assert path.read_bytes() == external and not list(path.parent.glob("*.bak"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_cleanup_after_commit_reports_installed_digest(tmp_path, monkeypatch):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    path.write_bytes(b"ai: {model: old}\n")
    saved = read_app_config_snapshot(meta)
    original_exit = Transaction.__exit__

    def failing_exit(self, kind, error, tb):
        result = original_exit(self, kind, error, tb)
        if error is None:
            raise OSError("post-commit unlock fixture")
        return result

    monkeypatch.setattr(Transaction, "__exit__", failing_exit)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "installed"})
    with pytest.raises(CommittedWriteError) as caught:
        write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert caught.value.installed_sha256 == hashlib.sha256(path.read_bytes()).digest()
    assert caught.value.report.committed and b"installed" in path.read_bytes()
    assert isinstance(caught.value.cause, OSError)
    assert caught.value.path == path and caught.value.__cause__ is caught.value.cause
    assert caught.value.report.files == {path: "new"}
    assert str(caught.value) == "Configuration saved, but the file must be reloaded before another save."


def test_unmanaged_endpoint_survives_other_edits(tmp_path):
    meta = meta_for(tmp_path, "yt2txt", selectable=False)
    path = meta.relative_path / "config.yaml"
    before = (
        b'ai:\n  api_base: "http://127.0.0.1:8000"\n'
        b'  api_key: "$EXAMPLE_API_KEY"\n'
        b'  endpoint: "/hand-written/value" # unmanaged by this editor\n'
        b'  model: "whisper-old"\n'
    )
    path.write_bytes(before)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "whisper-new"})
    installed = write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == before.replace(b'"whisper-old"', b'"whisper-new"')
    assert installed == hashlib.sha256(path.read_bytes()).digest()


def test_diff_does_not_materialize_omitted_fields(tmp_path):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    before = b"# Defaults are intentional\nai:\n  messages_default_max_tokens: 8192\n"
    path.write_bytes(before)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "endpoint": "/v1/messages"})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == before + b"  endpoint: /v1/messages\n"
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "chosen"})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == before + b"  endpoint: /v1/messages\n  model: chosen\n"
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "  "})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == before + b"  endpoint: /v1/messages\n"


@pytest.mark.parametrize("edit", ["protocol", "key", "model-leaf"])
def test_only_mode_toggle_removes_inactive_sections(tmp_path, edit):
    meta = meta_for(tmp_path, "textkit")
    path = meta.relative_path / "config.yaml"
    path.write_bytes(PROVIDER_ONLY)
    saved = read_app_config_snapshot(meta)
    if edit == "protocol":
        updates = {"endpoint": "/v1/messages"}
        expected = PROVIDER_ONLY + b"  endpoint: /v1/messages\n"
    elif edit == "key":
        updates = {"api_key": "replacement-key"}
        expected = PROVIDER_ONLY.replace(b'"$EXAMPLE_API_KEY"', b'"replacement-key"')
    else:
        updates = {"ocr_model": "vision-model"}
        expected = PROVIDER_ONLY.replace(
            b'    api_key_env: "VISION_KEY"\n',
            b'    api_key_env: "VISION_KEY"\n    model: vision-model\n',
        )
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), **updates})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == expected

    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "ocr_model": "temporary"})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "ocr_model": " "})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    expected = expected.replace(b"    model: vision-model\n", b"")
    assert path.read_bytes() == expected

    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "is_split_model": False, "model": "unified-model"})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    task_sections = (
        b'  ocr:\n    api_base: "https://vision.example.test"\n'
        b'    api_key_env: "VISION_KEY"\n  text:\n    api_key_env: "TEXT_KEY"\n'
    )
    unified = expected.replace(task_sections, b"").replace(
        b'"non-default-base-model"', b'"unified-model"'
    )
    assert path.read_bytes() == unified
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": " "})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == unified.replace(b'  model: "unified-model"\n', b"")

    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "unified-model"})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "is_split_model": True})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == unified.replace(b'  model: "unified-model"\n', b"") + b"  ocr: {}\n  text: {}\n"
    assert read_app_config_snapshot(meta).config.is_split_model


@pytest.mark.parametrize("split", [False, True])
def test_blank_active_models_pop_leaves_without_empty_scalars(tmp_path, split):
    meta = meta_for(tmp_path, "textkit")
    path = meta.relative_path / "config.yaml"
    before = (
        b'ai:\n  ocr:\n    api_key_env: "VISION_KEY"\n    model: old-ocr\n'
        b'  text:\n    model: old-text\n'
        if split else b'ai:\n  model: "old-model"\n  temperature: 0.2\n'
    )
    expected = (
        b'ai:\n  ocr:\n    api_key_env: "VISION_KEY"\n  text: {}\n'
        if split else b'ai:\n  temperature: 0.2\n'
    )
    path.write_bytes(before)
    saved = read_app_config_snapshot(meta)
    updates = {"ocr_model": " ", "text_model": ""} if split else {"model": " "}
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), **updates})
    write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert path.read_bytes() == expected


def test_checked_writer_returns_installed_bytes_digest_and_backup(tmp_path):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    before = b'ai:\n  model: "old" # keep\n'
    path.write_bytes(before)
    path.chmod(0o640)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "installed"})
    installed = write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert installed == hashlib.sha256(path.read_bytes()).digest()
    assert path.read_bytes() == b'ai:\n  model: "installed" # keep\n'
    backups = list(path.parent.glob("config.yaml.*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == before
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o640
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert not (path.parent / "config.yaml.bak").exists()
    assert not list(path.parent.glob(".*.tmp")) and not list(path.parent.glob("*.tmp*"))


def test_checked_writer_rechecks_under_transaction_lock(tmp_path, monkeypatch):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    path.write_bytes(b"ai: {model: old}\n")
    saved = read_app_config_snapshot(meta)
    external = b"ai: {model: hand-edit, endpoint: /v1/responses}\n"
    original_prepare = Transaction.prepare
    forwarded = []

    def raced_prepare(self, paths, expected):
        forwarded.append(expected.copy())
        path.write_bytes(external)
        return original_prepare(self, paths, expected)

    monkeypatch.setattr(Transaction, "prepare", raced_prepare)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "pending"})
    with pytest.raises(StaleDocumentError) as caught:
        write_app_config(meta, draft, baseline=saved.config, expected_sha256=saved.sha256)
    assert forwarded == [{path: saved.sha256}]
    assert caught.value.expected_sha256 == saved.sha256
    assert caught.value.actual_sha256 == hashlib.sha256(external).digest()
    assert path.read_bytes() == external and not list(path.parent.glob("*.bak"))
    assert not list(path.parent.glob(".*.tmp"))


def test_legacy_writer_branch_still_uses_fixed_backup(tmp_path):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    before = b'ai:\n  model: "old" # keep\n'
    path.write_bytes(before)
    path.chmod(0o640)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "legacy"})
    installed = write_app_config(meta, draft, baseline=saved.config)
    assert installed == hashlib.sha256(path.read_bytes()).digest()
    assert path.read_bytes() == b'ai:\n  model: "legacy" # keep\n'
    backup = path.with_name("config.yaml.bak")
    assert backup.read_bytes() == before and stat.S_IMODE(backup.stat().st_mode) == 0o640
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert not list(path.parent.glob("config.yaml.*.bak"))
    assert not list(path.parent.glob("*.tmp*"))


@pytest.mark.parametrize("boundary", ["raw", "forged"])
def test_diff_refuses_invalid_endpoint_before_mutating(tmp_path, boundary):
    meta = meta_for(tmp_path)
    config = AppAIConfig.model_construct(endpoint_raw="'bad'") if boundary == "raw" else AppAIConfig.model_construct(endpoint="/v1/forged")
    message = (
        "Invalid ai.endpoint must be explicitly repaired before saving."
        if boundary == "raw" else "Unsupported ai.endpoint value: '/v1/forged'."
    )
    tree = {"other": "untouched"}
    with pytest.raises(ValueError) as caught:
        _apply_ai_config(meta, tree, config, config)
    assert str(caught.value) == message and tree == {"other": "untouched"}


@pytest.mark.parametrize("checked", [False, True])
@pytest.mark.parametrize("boundary", ["raw", "forged"])
def test_writer_refuses_invalid_endpoint_before_noop(tmp_path, checked, boundary):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    raw = b"ai: {endpoint: bad}\n" if boundary == "raw" else b"ai: {model: m}\n"
    path.write_bytes(raw)
    saved = read_app_config_snapshot(meta)
    config = saved.config if boundary == "raw" else saved.config.model_copy(update={"endpoint": "/v1/forged"})
    message = (
        "Invalid ai.endpoint must be explicitly repaired before saving."
        if boundary == "raw" else "Unsupported ai.endpoint value: '/v1/forged'."
    )
    with pytest.raises(ConfigError) as caught:
        write_app_config(meta, config, baseline=config,
                         expected_sha256=saved.sha256 if checked else None)
    assert str(caught.value) == "Configuration save failed: " + message
    assert isinstance(caught.value.__cause__, ValueError)
    assert path.read_bytes() == raw and not list(path.parent.glob("*.bak"))


@pytest.mark.parametrize("checked", [False, True])
def test_endpoint_replacement_retains_quotes_and_order(tmp_path, checked):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    before = b'ai:\n  endpoint: "/v1/messages" # managed\n  model: "m"\n'
    path.write_bytes(before)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "endpoint": "/v1/responses"})
    write_app_config(meta, draft, baseline=saved.config,
                     expected_sha256=saved.sha256 if checked else None)
    assert path.read_bytes() == before.replace(b"/v1/messages", b"/v1/responses")
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "endpoint": None})
    write_app_config(meta, draft, baseline=saved.config,
                     expected_sha256=saved.sha256 if checked else None)
    assert path.read_bytes() == b'ai:\n  model: "m"\n'


@pytest.mark.parametrize("tree", [{}, {"ai": None}, {"other": "keep"}])
def test_diff_removal_does_not_create_absent_ai(tmp_path, tree):
    import copy

    before = copy.deepcopy(tree)
    _apply_ai_config(meta_for(tmp_path), tree, AppAIConfig(), AppAIConfig(model="removed"))
    assert tree == before


@pytest.mark.parametrize("expected", [b"short", "a" * 64, bytearray(32), 32])
def test_writer_validates_expected_digest_before_snapshot(tmp_path, monkeypatch, expected):
    import ai_manager.config.structured_config as sc

    meta = meta_for(tmp_path)
    monkeypatch.setattr(sc, "_snapshot", Mock(side_effect=AssertionError("invalid digest reached snapshot")))
    with pytest.raises(ConfigError) as caught:
        write_app_config(meta, AppAIConfig(), baseline=AppAIConfig(), expected_sha256=expected)
    assert str(caught.value) == "Configuration save failed: Expected digest must be a 32-byte SHA-256 value."
    assert isinstance(caught.value.__cause__, ValueError)


@pytest.mark.parametrize("checked", [False, True])
@pytest.mark.parametrize("error", [OSError("render fixture"), ValueError("render fixture")])
def test_writer_wraps_unowned_local_failures(tmp_path, monkeypatch, checked, error):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    before = b"ai: {model: old}\n"
    path.write_bytes(before)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "pending"})
    monkeypatch.setattr(yaml_manager, "render_app_config", Mock(side_effect=error))
    with pytest.raises(ConfigError) as caught:
        write_app_config(meta, draft, baseline=saved.config,
                         expected_sha256=saved.sha256 if checked else None)
    assert str(caught.value) == "Configuration save failed: render fixture"
    assert caught.value.__cause__ is error
    assert path.read_bytes() == before and not list(path.parent.glob("*.bak"))


@pytest.mark.parametrize("checked", [False, True])
@pytest.mark.parametrize("leaf", ["symlink", "dangling-symlink", "fifo"])
def test_writer_never_opens_nonregular_config_leaf(tmp_path, monkeypatch, checked, leaf):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    target = path.parent / "target.yaml"
    original = b"ai: {model: untouched}\n"
    (path.parent / "config.example.yaml").write_bytes(original)
    if leaf == "fifo":
        os.mkfifo(path)
    else:
        if leaf == "symlink":
            target.write_bytes(original)
        path.symlink_to(target)
    real_open = Path.open

    def guarded_open(candidate, *args, **kwargs):
        assert candidate != path, "nonregular leaf was opened"
        return real_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(ConfigLoadError):
        write_app_config(meta, AppAIConfig(model="pending"), baseline=AppAIConfig(),
                         expected_sha256=b"a" * 32 if checked else None)
    assert path.is_symlink() if leaf != "fifo" else stat.S_ISFIFO(path.lstat().st_mode)
    assert target.read_bytes() == original if leaf == "symlink" else not target.exists()
    assert not list(path.parent.glob("*.bak"))


def test_legacy_temp_is_private_before_fsync_and_cleaned_on_failure(tmp_path, monkeypatch):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    before = b"ai: {model: old}\n"
    path.write_bytes(before)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "pending"})
    modes = []

    def fail_fsync(fd):
        modes.append(stat.S_IMODE(os.fstat(fd).st_mode))
        raise OSError("fsync fixture")

    monkeypatch.setattr(yaml_manager.os, "fsync", fail_fsync)
    previous_umask = os.umask(0)
    try:
        with pytest.raises(Exception) as caught:
            write_app_config(meta, draft, baseline=saved.config)
    finally:
        os.umask(previous_umask)
    assert modes == [0o600]
    assert isinstance(caught.value, ConfigError) and str(caught.value) == "Configuration save failed: fsync fixture"
    assert path.read_bytes() == before and not list(path.parent.glob("*.tmp*"))


@pytest.mark.parametrize("boundary", ["raw", "forged"])
def test_compatibility_writer_refuses_invalid_endpoint_before_example_copy(tmp_path, boundary):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    (path.parent / "config.example.yaml").write_bytes(b"ai: {model: example}\n")
    config = AppAIConfig(endpoint_raw="'bad'") if boundary == "raw" else AppAIConfig.model_construct(endpoint="/v1/forged")
    with pytest.raises(ConfigError):
        write_app_config(meta, config, baseline=AppAIConfig())
    assert not path.exists() and not list(path.parent.glob("*.bak"))


def test_legacy_temp_collision_preserves_unowned_file(tmp_path, monkeypatch):
    from types import SimpleNamespace

    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    before = b"ai: {model: old}\n"
    path.write_bytes(before)
    saved = read_app_config_snapshot(meta)
    draft = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "pending"})
    monkeypatch.setattr(yaml_manager.uuid, "uuid4", lambda: SimpleNamespace(hex="aabbcc"))
    collision = path.with_name(f"{path.name}.tmp.{os.getpid()}_aabbcc")
    collision.write_bytes(b"unowned temporary file")
    with pytest.raises(ConfigError) as caught:
        write_app_config(meta, draft, baseline=saved.config)
    assert collision.exists() and collision.read_bytes() == b"unowned temporary file"
    assert isinstance(caught.value.__cause__, FileExistsError) and path.read_bytes() == before


def test_checked_writer_preserves_primary_unknown_error_after_cleanup_failure(tmp_path, monkeypatch):
    meta = meta_for(tmp_path)
    path = meta.relative_path / "config.yaml"
    before = b"ai: {model: old}\n"
    path.write_bytes(before)
    saved = read_app_config_snapshot(meta)
    candidate = AppAIConfig.model_validate({**saved.config.model_dump(), "model": "pending"})
    original_replace, original_release, original_sync = (
        Transaction.replace_all, Transaction._release, Transaction._fsync_dir
    )
    primary = []

    def replace(tx):
        try:
            return original_replace(tx)
        except TransactionError as exc:
            primary.append(exc)
            raise

    def sync(tx, parent):
        if tx._state in ("replacing", "rolling-back"):
            raise OSError("replace/restore fsync fixture")
        return original_sync(tx, parent)

    def release(tx):
        original_release(tx)
        raise OSError("cleanup fixture")

    monkeypatch.setattr(Transaction, "replace_all", replace)
    monkeypatch.setattr(Transaction, "_fsync_dir", sync)
    monkeypatch.setattr(Transaction, "_release", release)
    with pytest.raises(ConfigError) as caught:
        write_app_config(meta, candidate, baseline=saved.config, expected_sha256=saved.sha256)
    assert len(primary) == 1 and caught.value is primary[0]
    assert caught.value.report.files == {path: "unknown"}
    assert caught.value.report.phase == "rollback" and not caught.value.report.committed
    assert isinstance(caught.value.__cause__, OSError) and str(caught.value.__cause__) == "cleanup fixture"
    assert path.read_bytes() == before
    assert caught.value.report.backups[path].read_bytes() == before
    assert not list(path.parent.glob(".*.tmp"))
