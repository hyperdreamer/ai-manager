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


def test_five_widget_dispatch(qtbot, five_app_workspace):
    from ai_manager.ui.app_detail_view import AppDetailView
    from ai_manager.ui.main_window import MainWindow
    from ai_manager.ui.structured_config_view import StructuredConfigView

    window = MainWindow(workspace_root=five_app_workspace)
    qtbot.addWidget(window)
    assert list(window.views) == [
        "ai-grammar",
        "textkit",
        "yt2txt",
        "chat2api",
        "file-bridge",
    ]
    assert all(
        isinstance(window.views[a], AppDetailView)
        for a in ("ai-grammar", "textkit", "yt2txt")
    )
    assert all(
        isinstance(window.views[a], StructuredConfigView)
        for a in ("chat2api", "file-bridge")
    )
    assert window.sidebar.current_app_id() == "ai-grammar"
    assert not window.has_unsaved_changes()
