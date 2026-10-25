"""Isolated factories for endpoint-aware configuration tests.

These are test-only ownership shortcuts: ``meta_for`` builds a metadata record
whose launch directory lives under the caller's ``tmp_path`` (so no installed
service is ever touched) and ``snapshot`` installs an explicit digest/presence
pair instead of reading a file. Production code must derive both from the same
bytes it parses.
"""

from pathlib import Path

from ai_manager.config.models import AppAIConfig, AppMetadata, ConfigSnapshot


def meta_for(root: Path, app_id: str = "ai-grammar", *, selectable: bool = True) -> AppMetadata:
    launch = root / app_id / "backend"
    launch.mkdir(parents=True, exist_ok=True)
    return AppMetadata(id=app_id, display_name=app_id, relative_path=launch,
                       default_port=8000, supports_split_models=(app_id == "textkit"),
                       supports_protocol_selection=selectable)


def snapshot(config: AppAIConfig | None = None, *, present: bool = True,
             digest: bytes = b"s" * 32) -> ConfigSnapshot:
    return ConfigSnapshot(config if config is not None else AppAIConfig(), digest, present)
