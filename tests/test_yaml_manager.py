import hashlib
import os
import shutil
import stat
from hashlib import sha256
from pathlib import Path
import pytest
from ai_manager.config import yaml_manager
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.config_errors import (
    ConfigError,
    ConfigLoadError,
    ConfigShapeError,
    StaleDocumentError,
)
from ai_manager.config.yaml_manager import (
    _config_from_document,
    _get_yaml_engine,
    read_app_config,
    read_app_config_snapshot,
    render_app_config,
    write_app_config,
)
from ai_manager.config.models import AppAIConfig, AppMetadata
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
    new_cfg = AppAIConfig(
        api_base="https://tokenhub.tencentmaas.com",
        api_key="sk-new-token",
        model="deepseek-v3",
    )
    write_app_config(meta_grammar, new_cfg)

    # Re-read
    cfg = read_app_config(meta_grammar)
    assert cfg.api_base == "https://tokenhub.tencentmaas.com"
    assert cfg.model == "deepseek-v3"

    # Verify backup exists
    bak_path = temp_workspace / "ai-grammar" / "backend" / "config.yaml.bak"
    assert bak_path.exists()

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
    split_cfg = AppAIConfig(
        api_base="http://localhost:3000",
        api_key="sk-test",
        is_split_model=True,
        ocr_model="qwen-ocr",
        text_model="deepseek-chat",
    )
    write_app_config(meta_textkit, split_cfg)

    read_split = read_app_config(meta_textkit)
    assert read_split.is_split_model is True
    assert read_split.ocr_model == "qwen-ocr"
    assert read_split.text_model == "deepseek-chat"

    # 2. Switch split back to unified
    unified_cfg = AppAIConfig(
        api_base="http://localhost:3000",
        api_key="sk-test",
        is_split_model=False,
        model="claude-3-5-sonnet",
    )
    write_app_config(meta_textkit, unified_cfg)

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

    monkeypatch.setattr(yaml_manager, "_render_document", spy)
    write_app_config(meta, read_app_config(meta))
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
    cfg = read_app_config(meta)
    write_app_config(meta, cfg, digest)
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
    cfg = read_app_config(meta).model_copy(update={"model": "checked"})
    digest = hashlib.sha256(original).digest()
    path.write_bytes(original + b"# hand edit\n")
    with pytest.raises(StaleDocumentError):
        write_app_config(meta, cfg, digest)
    assert path.read_bytes() == original + b"# hand edit\n"
    path.unlink()
    with pytest.raises(StaleDocumentError):
        write_app_config(meta, cfg, digest)
    assert not path.exists()
    path.write_bytes(original)
    assert write_app_config(meta, cfg, digest) is None
    assert read_app_config(meta).model == "checked"
    assert list(path.parent.glob("config.yaml.*.bak")) and not (path.parent / "config.yaml.bak").exists()
    assert write_app_config(meta, cfg) is None
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
