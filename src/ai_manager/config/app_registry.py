from pathlib import Path
from typing import Dict
from ai_manager.config.models import AppMetadata


def get_managed_apps(workspace_root: Path) -> Dict[str, AppMetadata]:
    """Return the five supervised applications in display order; free-tts remains excluded."""
    return {
        "ai-grammar": AppMetadata(
            id="ai-grammar",
            display_name="ai-grammar",
            relative_path=workspace_root / "ai-grammar" / "backend",
            config_file_name="config.yaml",
            example_config_file_name="config.example.yaml",
            default_port=8766,
            supports_split_models=False,
            description="Grammar checking, polishing, and translation backend",
            config_kind="llm",
        ),
        "textkit": AppMetadata(
            id="textkit",
            display_name="textkit",
            relative_path=workspace_root / "textkit" / "backend",
            config_file_name="config.yaml",
            example_config_file_name="config.example.yaml",
            default_port=8765,
            supports_split_models=True,
            description="Text deduplication, processing, and OCR backend",
            config_kind="llm",
        ),
        "yt2txt": AppMetadata(
            id="yt2txt",
            display_name="yt2txt",
            relative_path=workspace_root / "yt2txt" / "backend",
            config_file_name="config.yaml",
            example_config_file_name="config.example.yaml",
            default_port=8666,
            supports_split_models=False,
            description="YouTube media audio transcription backend",
            config_kind="llm",
        ),
        "chat2api": AppMetadata(
            id="chat2api",
            display_name="chat2api",
            relative_path=workspace_root / "chat2api",
            config_file_name="config.json",
            example_config_file_name="config.example.json",
            default_port=8000,
            supports_split_models=False,
            description="Local OpenAI-compatible gateway for web AI providers",
            config_kind="chat2api",
        ),
        "file-bridge": AppMetadata(
            id="file-bridge",
            display_name="file-bridge",
            relative_path=workspace_root / "file-bridge",
            config_file_name="config.yaml",
            example_config_file_name="config.example.yaml",
            default_port=8964,
            supports_split_models=False,
            description="Local file bridge for saving text and completing paths",
            config_kind="file-bridge",
        ),
    }
