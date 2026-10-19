"""Integration tests for MainWindow tray, settings and quit behaviour.

The shared ``five_app_workspace`` fixture supplies the five registered
application directories so these lifecycle assertions cover the structured
views too. Settings loading/persistence is isolated so the developer's real
``~/.config/ai-manager/settings.json`` is never read or written.
"""

import pytest
from PyQt6.QtWidgets import QMessageBox

from ai_manager.config.models import ThemeMode, UserSettings
from ai_manager.ui import main_window as main_window_module
from ai_manager.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot, five_app_workspace, monkeypatch):
    """Build a MainWindow against the five-app workspace with isolated settings."""
    monkeypatch.setattr(main_window_module, "load_user_settings", lambda: UserSettings())
    monkeypatch.setattr(main_window_module, "save_user_settings", lambda settings: None)

    win = MainWindow(workspace_root=five_app_workspace)
    qtbot.addWidget(win)
    return win


def _dirty_draft(window: MainWindow) -> None:
    """Make both an LLM and a structured app dirty in one call."""
    window.views["ai-grammar"]._model_combo.setEditText("tray-test-model")
    window.views["chat2api"]._fields[("server", "port")].edit.setText("8123")


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


def test_close_event_ignored_and_hides_when_close_to_tray(
    window, mock_tray_available
):
    window.settings.close_to_tray = True
    window.settings.first_close_notice_shown = True

    window.show()
    _dirty_draft(window)
    assert window.has_unsaved_changes()

    assert window.close() is False
    assert window.isVisible() is False
    # Draft state must survive the close-to-tray interception.
    assert window.has_unsaved_changes() is True


def test_close_event_accepts_when_force_quit(window, mock_tray_available):
    window.settings.close_to_tray = True
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


def test_non_tray_close_exits_application(window, monkeypatch):
    """Closing without close-to-tray must quit the process, not orphan it.

    ``main.py`` sets ``quitOnLastWindowClosed(False)`` so accepting a close is
    not sufficient on its own; the exit path must call ``QApplication.quit``.
    """
    window.settings.close_to_tray = False
    _dirty_draft(window)
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Discard),
    )

    quit_calls = []
    fake_instance = type(
        "FakeAppInstance", (), {"quit": lambda self: quit_calls.append(True)}
    )
    fake_app = type(
        "FakeApp", (), {"instance": staticmethod(lambda: fake_instance())}
    )
    monkeypatch.setattr(main_window_module, "QApplication", fake_app)

    assert window.close() is True
    assert window._force_quit is True
    assert quit_calls == [True]


def test_non_tray_close_without_unsaved_changes_quits(window, monkeypatch):
    """The no-unsaved-variant of the non-tray exit path must also quit."""
    window.settings.close_to_tray = False
    assert window.has_unsaved_changes() is False

    quit_calls = []
    fake_instance = type(
        "FakeAppInstance", (), {"quit": lambda self: quit_calls.append(True)}
    )
    fake_app = type(
        "FakeApp", (), {"instance": staticmethod(lambda: fake_instance())}
    )
    monkeypatch.setattr(main_window_module, "QApplication", fake_app)

    assert window.close() is True
    assert window._force_quit is True
    assert quit_calls == [True]


def test_initial_toggle_action_text_reflects_hidden_window(window):
    assert window.tray_manager._toggle_action.text() == "Show ai-manager"


def test_show_and_hide_events_sync_toggle_action_text(window):
    window.show()
    assert window.tray_manager._toggle_action.text() == "Hide ai-manager"

    window.hide()
    assert window.tray_manager._toggle_action.text() == "Show ai-manager"


def test_start_minimized_override_and_default(qtbot, window):
    overridden = MainWindow(
        workspace_root=window.workspace_root, start_minimized_override=True
    )
    qtbot.addWidget(overridden)
    assert overridden.is_minimized_at_startup is True

    defaulted = MainWindow(workspace_root=window.workspace_root)
    qtbot.addWidget(defaulted)
    assert defaulted.settings.start_minimized is False
    assert defaulted.is_minimized_at_startup is False


def test_structured_dirty_quit_cancel_keeps_raw_draft(
    qtbot, five_app_workspace, monkeypatch
):
    from ai_manager.ui import main_window as mw

    window = mw.MainWindow(workspace_root=five_app_workspace)
    qtbot.addWidget(window)
    view = window.views["chat2api"]
    view._on_raw_options_changed(view._model.rows[0].id, "{broken")
    exited = []
    monkeypatch.setattr(window, "_exit_application", lambda: exited.append(True))
    monkeypatch.setattr(
        mw.QMessageBox, "question", lambda *a: mw.QMessageBox.StandardButton.Cancel
    )
    window.handle_quit()
    assert not exited and window.has_unsaved_changes()
    assert view.get_current_draft().raw_option_edits == {"echo-1": "{broken"}
