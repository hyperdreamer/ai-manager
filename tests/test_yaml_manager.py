import shutil
from pathlib import Path
import pytest
from ai_manager.config.models import AppAIConfig, AppMetadata
from ai_manager.config.yaml_manager import read_app_config, write_app_config


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
