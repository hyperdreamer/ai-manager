import copy
import io
import os
import shutil
import stat
import uuid
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ai_manager.config.config_errors import StaleDocumentError, require_llm
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
    require_llm(app_meta)
    cfg_path = get_config_path(app_meta)
    if not cfg_path.exists():
        example_path = get_example_config_path(app_meta)
        if example_path.exists():
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(example_path, cfg_path)
        else:
            raise FileNotFoundError(f"Neither {cfg_path} nor {example_path} exists.")
    return cfg_path


def _config_from_document(doc: MutableMapping[str, Any]) -> AppAIConfig:
    """Normalize an already-parsed LLM config tree without touching disk."""
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


def read_app_config(app_meta: AppMetadata) -> AppAIConfig:
    """Reads and parses an AppAIConfig from the application's config.yaml."""
    require_llm(app_meta)
    cfg_path = ensure_config_exists(app_meta)
    yaml = _get_yaml_engine()
    with open(cfg_path, "r", encoding="utf-8") as f:
        doc = yaml.load(f) or {}
    return _config_from_document(doc)


def _render_document(doc: MutableMapping[str, Any]) -> bytes:
    stream = io.StringIO()
    _get_yaml_engine().dump(doc, stream)
    return stream.getvalue().encode("utf-8")


def render_app_config(meta: AppMetadata, doc: MutableMapping[str, Any], mutate: Callable[[MutableMapping[str, Any]], None]) -> bytes:
    require_llm(meta)
    candidate = copy.deepcopy(doc)
    mutate(candidate)
    return _render_document(candidate)


def _apply_ai_config(meta: AppMetadata, doc: MutableMapping[str, Any], new_config: AppAIConfig) -> None:
    if "ai" not in doc or not isinstance(doc["ai"], dict):
        doc["ai"] = CommentedMap()
    ai_sec = doc["ai"]
    ai_sec["api_base"] = new_config.api_base
    ai_sec["api_key"] = new_config.api_key
    if new_config.is_split_model and meta.supports_split_models:
        ai_sec.pop("model", None)
        if not isinstance(ai_sec.get("ocr"), dict):
            ai_sec["ocr"] = CommentedMap()
        if not isinstance(ai_sec.get("text"), dict):
            ai_sec["text"] = CommentedMap()
        ai_sec["ocr"]["model"] = new_config.ocr_model or ""
        ai_sec["text"]["model"] = new_config.text_model or ""
    else:
        ai_sec.pop("ocr", None)
        ai_sec.pop("text", None)
        ai_sec["model"] = new_config.model or ""


def write_app_config(app_meta: AppMetadata, new_config: AppAIConfig, expected_sha256: bytes | None = None) -> None:
    """Atomically updates the application's config.yaml with comment preservation."""
    require_llm(app_meta)
    if expected_sha256 is not None:
        from ai_manager.config.structured_config import _snapshot
        from ai_manager.config.transaction import Transaction
        cfg_path, raw, _mode, _reasons = _snapshot(get_config_path(app_meta))
        if raw is None:
            raise StaleDocumentError(cfg_path, expected_sha256, None)
        doc = _get_yaml_engine().load(raw.decode("utf-8"))
        if doc is None:
            doc = CommentedMap()
        rendered = render_app_config(app_meta, doc, lambda tree: _apply_ai_config(app_meta, tree, new_config))
        with Transaction() as tx:
            tx.prepare([cfg_path], {cfg_path: expected_sha256})
            tx.backups()
            tx.stage({cfg_path: rendered})
            tx.replace_all()
        return
    cfg_path = ensure_config_exists(app_meta)
    doc = _get_yaml_engine().load(cfg_path.read_text(encoding="utf-8"))
    if doc is None:
        doc = CommentedMap()
    rendered = render_app_config(app_meta, doc, lambda tree: _apply_ai_config(app_meta, tree, new_config))
    backup_path = cfg_path.with_name(f"{cfg_path.name}.bak")
    shutil.copy2(cfg_path, backup_path)
    temp_path = cfg_path.with_name(f"{cfg_path.name}.tmp.{os.getpid()}_{uuid.uuid4().hex[:6]}")
    try:
        with open(temp_path, "wb") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        if cfg_path.exists():
            os.chmod(temp_path, stat.S_IMODE(cfg_path.stat().st_mode))
        os.replace(temp_path, cfg_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
