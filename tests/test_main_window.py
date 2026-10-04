import shutil
from pathlib import Path
from ai_manager.config.models import ThemeMode
from ai_manager.ui.main_window import MainWindow


def test_main_window_init_and_navigation(qtbot, tmp_path):
    fixtures_dir = Path(__file__).parent / "fixtures"
    for d in ["ai-grammar", "textkit", "yt2txt"]:
        (tmp_path / d / "backend").mkdir(parents=True)

    shutil.copy2(fixtures_dir / "ai_grammar_config.yaml", tmp_path / "ai-grammar" / "backend" / "config.yaml")
    shutil.copy2(fixtures_dir / "textkit_unified_config.yaml", tmp_path / "textkit" / "backend" / "config.yaml")
    shutil.copy2(fixtures_dir / "yt2txt_config.yaml", tmp_path / "yt2txt" / "backend" / "config.yaml")

    window = MainWindow(workspace_root=tmp_path)
    qtbot.addWidget(window)

    assert window.sidebar.current_app_id() == "ai-grammar"
    assert not window.has_unsaved_changes()

    # Modify ai-grammar draft
    window.views["ai-grammar"]._model_combo.setEditText("new-test-model")
    assert window.has_unsaved_changes()
    assert "ai-grammar" in window.sidebar._dirty_apps

    # Switch to textkit
    window.sidebar.select_app("textkit")
    assert window.sidebar.current_app_id() == "textkit"

    # ai-grammar changes are still preserved in draft
    assert window._draft_configs["ai-grammar"].model == "new-test-model"

    # Theme toggle
    prev_theme = window.settings.theme
    window._toggle_theme()
    assert window.settings.theme != prev_theme
