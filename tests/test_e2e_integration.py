from pathlib import Path
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.models import AppAIConfig
from ai_manager.config.yaml_manager import read_app_config, write_app_config
from ai_manager.services.supervisor import parse_supervisor_status
from ai_manager.ui.main_window import MainWindow
from ai_manager.utils.path_locator import find_ai_workspace_root


def test_full_workspace_integration(qtbot):
    workspace = find_ai_workspace_root()
    apps = get_managed_apps(workspace)

    assert "ai-grammar" in apps
    assert "textkit" in apps
    assert "yt2txt" in apps

    # Verify real configurations can be read without crashing
    for app_id, meta in apps.items():
        cfg = read_app_config(meta)
        assert cfg.api_base is not None
        assert cfg.api_key is not None

    # Verify MainWindow can instantiate against the live workspace
    window = MainWindow(workspace_root=workspace)
    qtbot.addWidget(window)
    assert window.sidebar.current_app_id() == "ai-grammar"
