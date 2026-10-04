"""Integration tests for MainWindow tray, settings and quit behaviour.

The workspace fixture setup mirrors ``tests/test_main_window.py`` so the
window builds against the same fake managed applications. Settings
loading/persistence is isolated so the developer's real
``~/.config/ai-manager/settings.json`` is never read or written.
"""

import shutil
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QSystemTrayIcon

from ai_manager.config.models import ThemeMode, UserSettings
from ai_manager.ui import main_window as main_window_module
from ai_manager.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    """Build a MainWindow against copied fixtures with isolated settings."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    for d in ["ai-grammar", "textkit", "yt2txt"]:
        (tmp_path / d / "backend").mkdir(parents=True)

    shutil.copy2(
        fixtures_dir / "ai_grammar_config.yaml",
        tmp_path / "ai-grammar" / "backend" / "config.yaml",
    )
    shutil.copy2(
        fixtures_dir / "textkit_unified_config.yaml",
        tmp_path / "textkit" / "backend" / "config.yaml",
    )
    shutil.copy2(
        fixtures_dir / "yt2txt_config.yaml",
        tmp_path / "yt2txt" / "backend" / "config.yaml",
    )

    monkeypatch.setattr(main_window_module, "load_user_settings", lambda: UserSettings())
    monkeypatch.setattr(main_window_module, "save_user_settings", lambda settings: None)

    win = MainWindow(workspace_root=tmp_path)
    qtbot.addWidget(win)
    return win


def _dirty_draft(window: MainWindow) -> None:
    window.views["ai-grammar"]._model_combo.setEditText("tray-test-model")


def test_toolbar_has_settings_button_that_opens_dialog(window, monkeypatch):
    assert window._settings_btn is not None
    assert "Settings" in window._settings_btn.text()

    calls = []
    monkeypatch.setattr(
        main_window_module.SettingsDialog,
        "exec",
        lambda self: calls.append(True) or 0,
    )

    window._settings_btn.click()

    assert calls == [True]


def test_close_event_ignored_and_hides_when_close_to_tray(window, monkeypatch):
    window.settings.close_to_tray = True
    window.settings.first_close_notice_shown = True
    monkeypatch.setattr(
        QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True)
    )

    window.show()
    _dirty_draft(window)
    assert window.has_unsaved_changes()

    assert window.close() is False
    assert window.isVisible() is False
    # Draft state must survive the close-to-tray interception.
    assert window.has_unsaved_changes() is True


def test_close_event_accepts_when_force_quit(window, monkeypatch):
    window.settings.close_to_tray = True
    monkeypatch.setattr(
        QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True)
    )
    window._force_quit = True

    assert window.close() is True


def test_on_settings_saved_updates_poll_interval_and_theme(window):
    new_theme = (
        ThemeMode.LIGHT if window.settings.theme == ThemeMode.DARK else ThemeMode.DARK
    )
    new_settings = window.settings.model_copy()
    new_settings.poll_interval_ms = 10000
    new_settings.theme = new_theme

    window._on_settings_saved(new_settings)

    assert window._poll_timer.interval() == 10000
    assert window.settings.theme == new_theme
    assert window.settings.poll_interval_ms == 10000


def test_toggle_window_visibility_hides_visible_active_window(window, monkeypatch):
    window.show()
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)

    assert window.isVisible() is True

    window.toggle_window_visibility()

    assert window.isVisible() is False
