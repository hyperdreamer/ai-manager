import copy
import hashlib
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
from ai_manager.config.config_errors import (
    ConfigError,
    ConfigLoadError,
    ConfigShapeError,
    StaleDocumentError,
    require_llm,
)
from ai_manager.config.models import AppAIConfig, AppMetadata, ConfigSnapshot
from ai_manager.config.protocols import is_valid_endpoint


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


def _parse_llm_document(path: Path, raw: bytes) -> MutableMapping[str, Any]:
    """Parse and shape-check LLM bytes that were already read from ``path``."""
    try:
        text = raw.decode("utf-8")
        engine = _get_yaml_engine()
        # A duplicated managed key makes the rendered diff ambiguous, so the whole
        # document is refused rather than silently resolving to the last value.
        engine.allow_duplicate_keys = False
        doc = engine.load(text)
        # ``load`` returns None for both an empty document and an explicit null
        # scalar. Compose the SAME text to tell them apart without a second read:
        # no root node is empty, a scalar/sequence root is a shape error.
        if doc is None and engine.compose(text) is None:
            doc = CommentedMap()
        if not isinstance(doc, MutableMapping):
            raise ConfigShapeError(
                path,
                "Configuration root must be a mapping; save is disabled.",
                "non-dict-root",
            )
        ai = doc.get("ai")
        if ai is not None and not isinstance(ai, MutableMapping):
            raise ConfigShapeError(
                path,
                "AI must be a mapping when present; save is disabled.",
                "load-error",
            )
        return doc
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigLoadError(path, str(exc)) from exc


def _config_from_document(doc: MutableMapping[str, Any], meta: AppMetadata) -> AppAIConfig:
    """Normalize an already-parsed LLM config tree without touching disk."""
    require_llm(meta)
    if not isinstance(doc, MutableMapping):
        raise ValueError("Configuration root must be a mapping; save is disabled.")
    ai = doc.get("ai")
    if ai is None:
        ai = {}
    elif not isinstance(ai, MutableMapping):
        raise ValueError("AI must be a mapping when present; save is disabled.")

    # Endpoint ownership comes from metadata, never from the document's shape. A
    # present-but-unusable value is kept as raw evidence so a later explicit Auto
    # selection can force the key's removal; it is never fed to the literal field.
    endpoint = endpoint_raw = None
    if meta.supports_protocol_selection and "endpoint" in ai:
        value = ai["endpoint"]
        if is_valid_endpoint(value):
            endpoint = value
        else:
            endpoint_raw = repr(value)

    ocr, text = ai.get("ocr"), ai.get("text")
    split = meta.supports_split_models and any(
        isinstance(section, MutableMapping) for section in (ocr, text)
    )

    def model_value(value: object) -> str | None:
        return str(value) if value else None

    return AppAIConfig(
        api_base=str(ai.get("api_base") or "http://127.0.0.1:3000"),
        api_key=str(ai.get("api_key") or ""),
        model=None if split else model_value(ai.get("model")),
        is_split_model=split,
        ocr_model=model_value(ocr.get("model")) if split and isinstance(ocr, MutableMapping) else None,
        text_model=model_value(text.get("model")) if split and isinstance(text, MutableMapping) else None,
        endpoint=endpoint,
        endpoint_raw=endpoint_raw,
    )


def read_app_config_snapshot(app_meta: AppMetadata) -> ConfigSnapshot:
    """Read one LLM config without creating it, from a single byte snapshot."""
    # Imported locally: structured_config imports this module for the YAML engine.
    from ai_manager.config.structured_config import _snapshot

    require_llm(app_meta)
    cfg_path = get_config_path(app_meta)
    try:
        resolved, raw, _mode, _reasons = _snapshot(cfg_path)
        if raw is None:
            raise ConfigLoadError(cfg_path, "Configuration file is missing.")
        tree = _parse_llm_document(resolved, raw)
        config = _config_from_document(tree, app_meta)
        ai = tree.get("ai")
        present = isinstance(ai, MutableMapping) and "api_base" in ai
        return ConfigSnapshot(config, hashlib.sha256(raw).digest(), present)
    except ConfigError:
        raise
    except Exception as exc:
        # A read/display failure must never turn into an owned default draft.
        raise ConfigLoadError(cfg_path, str(exc)) from exc


def read_app_config(app_meta: AppMetadata) -> AppAIConfig:
    """Compatibility reader: create from the example once, then snapshot-read."""
    require_llm(app_meta)
    ensure_config_exists(app_meta)
    return read_app_config_snapshot(app_meta).config.model_copy(deep=True)


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
