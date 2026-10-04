from pathlib import Path
from typing import Dict
from ai_manager.config.models import AppMetadata


def get_managed_apps(workspace_root: Path) -> Dict[str, AppMetadata]:
    """Returns registered target apps under workspace_root, excluding free-tts and file-bridge."""
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
        ),
    }
