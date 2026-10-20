from unittest.mock import MagicMock, call

from ai_manager import __version__
from ai_manager.config.models import (
    ServiceRunState,
    ServiceStatus,
    SupervisorStatus,
    ThemeMode,
)
from ai_manager.ui import main_window as main_window_module
from ai_manager.ui.main_window import MainWindow


def make_test_window(qtbot, five_app_workspace):
    window = MainWindow(workspace_root=five_app_workspace)
    qtbot.addWidget(window)
    window.sidebar.update_status = MagicMock()
    for view in window.views.values():
        view.update_service_status = MagicMock()
    return window


def test_main_window_init_and_navigation(qtbot, five_app_workspace):
    window = MainWindow(workspace_root=five_app_workspace)
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


def test_status_normalization_forwards_reported_and_missing_apps(
    qtbot, five_app_workspace
):
    window = make_test_window(qtbot, five_app_workspace)
    reported = ServiceStatus(
        service_id="ai-grammar", state=ServiceRunState.RUNNING,
        pid=123, log_path="/tmp/grammar.log",
    )
    window._on_supervisor_status(
        SupervisorStatus(is_running=True, supervisor_pid=9,
                         services={"ai-grammar": reported})
    )
    assert window.sidebar.update_status.call_count == len(window.apps)
    for app_id in window.apps:
        forwarded = window.sidebar.update_status.call_args_list[
            list(window.apps).index(app_id)
        ].args[1]
        assert forwarded.service_id == app_id
        if app_id == "ai-grammar":
            assert forwarded is reported
        else:
            assert forwarded.state == ServiceRunState.UNKNOWN
            assert forwarded.log_path is None
            assert window.views[app_id].update_service_status.call_args.args[0] is forwarded


def test_inactive_supervisor_sends_unknown_to_every_managed_app(
    qtbot, five_app_workspace
):
    window = make_test_window(qtbot, five_app_workspace)
    residual = ServiceStatus(
        service_id="ai-grammar", state=ServiceRunState.STOPPED,
        pid=None, log_path="/tmp/grammar.log",
    )
    window._on_supervisor_status(
        SupervisorStatus(is_running=False, services={"ai-grammar": residual})
    )
    for app_id in window.apps:
        forwarded = next(
            call.args[1] for call in window.sidebar.update_status.call_args_list
            if call.args[0] == app_id
        )
        assert forwarded == ServiceStatus(
            service_id=app_id, state=ServiceRunState.UNKNOWN
        )
        assert window.views[app_id].update_service_status.call_args.args[0] == forwarded


def test_main_window_title_includes_version(qtbot, tmp_path):
    window = make_test_window(qtbot, tmp_path)
    assert window.windowTitle() == (
        f"ai-manager v{__version__} — AI Provider Configuration & Service Controller"
    )
    assert f"v{__version__}" in window.windowTitle()
    assert "&" in window.windowTitle()


def test_title_propagates_patched_source_version(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(main_window_module, "__version__", "9.8.7")
    window = make_test_window(qtbot, tmp_path)
    assert window.windowTitle() == (
        "ai-manager v9.8.7 — AI Provider Configuration & Service Controller"
    )


def test_open_about_dialog_constructs_fresh_modal(qtbot, tmp_path, monkeypatch):
    window = make_test_window(qtbot, tmp_path)
    first, second = MagicMock(), MagicMock()
    factory = MagicMock(side_effect=[first, second])
    monkeypatch.setattr(main_window_module, "AboutDialog", factory)

    window.open_about_dialog()
    window.open_about_dialog()

    assert factory.call_args_list == [call(window), call(window)]
    first.exec.assert_called_once_with()
    second.exec.assert_called_once_with()


def test_tray_about_request_opens_about_dialog(qtbot, tmp_path, monkeypatch):
    window = make_test_window(qtbot, tmp_path)
    instance = MagicMock()
    factory = MagicMock(return_value=instance)
    monkeypatch.setattr(main_window_module, "AboutDialog", factory)

    window.tray_manager._about_action.trigger()

    factory.assert_called_once_with(window)
    instance.exec.assert_called_once_with()
