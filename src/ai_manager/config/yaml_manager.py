import os
import shutil
import stat
import uuid
from pathlib import Path
from typing import Optional
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ai_manager.config.models import AppAIConfig, AppMetadata


def _get_yaml_engine() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    return yaml


def get_config_path(app_meta: AppMetadata) -> Path:
    return app_meta.relative_path / app_meta.config_file_name


def get_example_config_path(app_meta: AppMetadata) -> Path:
    return app_meta.relative_path / app_meta.example_config_file_name


def ensure_config_exists(app_meta: AppMetadata) -> Path:
    """Ensures config.yaml exists; if missing, copies from config.example.yaml."""
    cfg_path = get_config_path(app_meta)
    if not cfg_path.exists():
        example_path = get_example_config_path(app_meta)
        if example_path.exists():
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(example_path, cfg_path)
        else:
            raise FileNotFoundError(f"Neither {cfg_path} nor {example_path} exists.")
    return cfg_path


def read_app_config(app_meta: AppMetadata) -> AppAIConfig:
    """Reads and parses an AppAIConfig from the application's config.yaml."""
    cfg_path = ensure_config_exists(app_meta)
    yaml = _get_yaml_engine()
    with open(cfg_path, "r", encoding="utf-8") as f:
        doc = yaml.load(f) or {}

    ai_section = doc.get("ai") or {}
    api_base = str(ai_section.get("api_base") or "http://127.0.0.1:3000")
    api_key = str(ai_section.get("api_key") or "")

    # Check for split models (textkit)
    ocr_section = ai_section.get("ocr") if isinstance(ai_section.get("ocr"), dict) else None
    text_section = ai_section.get("text") if isinstance(ai_section.get("text"), dict) else None

    if ocr_section is not None or text_section is not None:
        ocr_model = ocr_section.get("model") if ocr_section else None
        text_model = text_section.get("model") if text_section else None
        return AppAIConfig(
            api_base=api_base,
            api_key=api_key,
            is_split_model=True,
            ocr_model=str(ocr_model) if ocr_model else None,
            text_model=str(text_model) if text_model else None,
            model=None,
        )

    # Single unified model mode
    single_model = ai_section.get("model")
    return AppAIConfig(
        api_base=api_base,
        api_key=api_key,
        is_split_model=False,
        model=str(single_model) if single_model else None,
        ocr_model=None,
        text_model=None,
    )


def write_app_config(app_meta: AppMetadata, new_config: AppAIConfig) -> None:
    """Atomically updates the application's config.yaml with comment preservation."""
    cfg_path = ensure_config_exists(app_meta)
    yaml = _get_yaml_engine()

    with open(cfg_path, "r", encoding="utf-8") as f:
        doc = yaml.load(f)

    if doc is None:
        doc = CommentedMap()

    if "ai" not in doc or not isinstance(doc["ai"], dict):
        doc["ai"] = CommentedMap()

    ai_sec = doc["ai"]
    ai_sec["api_base"] = new_config.api_base
    ai_sec["api_key"] = new_config.api_key

    if new_config.is_split_model and app_meta.supports_split_models:
        if "model" in ai_sec:
            del ai_sec["model"]
        if "ocr" not in ai_sec or not isinstance(ai_sec["ocr"], dict):
            ai_sec["ocr"] = CommentedMap()
        if "text" not in ai_sec or not isinstance(ai_sec["text"], dict):
            ai_sec["text"] = CommentedMap()
        ai_sec["ocr"]["model"] = new_config.ocr_model or ""
        ai_sec["text"]["model"] = new_config.text_model or ""
    else:
        if "ocr" in ai_sec:
            del ai_sec["ocr"]
        if "text" in ai_sec:
            del ai_sec["text"]
        ai_sec["model"] = new_config.model or ""

    # Atomic write protocol
    backup_path = cfg_path.with_name(f"{cfg_path.name}.bak")
    shutil.copy2(cfg_path, backup_path)

    temp_path = cfg_path.with_name(f"{cfg_path.name}.tmp.{os.getpid()}_{uuid.uuid4().hex[:6]}")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.dump(doc, f)
            f.flush()
            os.fsync(f.fileno())

        # Copy mode if original exists
        if cfg_path.exists():
            orig_mode = stat.S_IMODE(cfg_path.stat().st_mode)
            os.chmod(temp_path, orig_mode)

        os.replace(temp_path, cfg_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
