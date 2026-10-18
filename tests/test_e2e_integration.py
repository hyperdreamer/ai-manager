import json

from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.yaml_manager import _get_yaml_engine, read_app_config


def test_full_workspace_integration(five_app_workspace):
    apps = get_managed_apps(five_app_workspace)
    for meta in apps.values():
        path = meta.relative_path / meta.config_file_name
        if meta.config_kind == "llm":
            cfg = read_app_config(meta)
            assert cfg.api_base == "http://127.0.0.1:8000"
            assert cfg.api_key == "$CHAT2API_TOKEN"
        elif meta.config_kind == "chat2api":
            doc = json.loads(path.read_bytes())
            assert doc["server"]["auth_token_env"] is None
            assert "options" not in doc["models"]["echo-1"]
        elif meta.config_kind == "file-bridge":
            doc = _get_yaml_engine().load(path.read_text())
            assert doc["save_root"] == "../storage"
            assert doc["port"] == 8964
        else:
            raise AssertionError(meta.config_kind)
