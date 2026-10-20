"""Unit tests for the SystemTrayManager component.

These tests must never require a real system tray host: the availability
probe is monkeypatched and the tray icon itself is stubbed where needed.
"""

import pytest
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QSystemTrayIcon

from ai_manager.ui import system_tray
from ai_manager.ui.system_tray import SystemTrayManager


@pytest.fixture
def manager(qapp):
    """A SystemTrayManager instance (QApplication is provided by pytest-qt)."""
    return SystemTrayManager()


def test_context_menu_order_and_structure(manager):
    actions = manager._context_menu.actions()
    assert [a.text() for a in actions] == [
        "Show ai-manager",
        "",
        "Start All Supervised Services",
        "Stop All Supervised Services",
        "",
        "⚙ Settings...",
        "About ai-manager",
        "",
        "Quit ai-manager",
    ]
    assert [index for index, action in enumerate(actions)
            if action.isSeparator()] == [1, 4, 7]
    assert actions[6] is manager._about_action


@pytest.mark.parametrize(
    "attr, signal_name",
    [
        ("_toggle_action", "toggle_window_requested"),
        ("_start_all_action", "start_all_services_requested"),
        ("_stop_all_action", "stop_all_services_requested"),
        ("_settings_action", "open_settings_requested"),
        ("_about_action", "about_requested"),
        ("_quit_action", "quit_requested"),
    ],
)
def test_menu_action_emits_expected_signal(qtbot, manager, attr, signal_name):
    action = getattr(manager, attr)
    signal = getattr(manager, signal_name)
    emissions = []
    signal.connect(lambda *args: emissions.append(args))
    with qtbot.waitSignal(signal, timeout=1000):
        action.trigger()
    assert emissions == [()]


def test_single_click_activation_emits_toggle(qtbot, manager):
    with qtbot.waitSignal(manager.toggle_window_requested, timeout=1000):
        manager._tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)


def test_context_activation_does_not_toggle(qtbot, manager):
    with qtbot.assertNotEmitted(manager.toggle_window_requested, wait=100):
        manager._tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.Context)


def test_update_visibility_action_text(manager):
    actions = manager._context_menu.actions()
    snapshot = [action.text() for action in actions]

    manager.update_visibility_action_text(True)
    assert manager._toggle_action.text() == "Hide ai-manager"
    current = manager._context_menu.actions()
    assert current == actions
    assert [action.text() for action in current] == [
        "Hide ai-manager", *snapshot[1:]
    ]

    manager.update_visibility_action_text(False)
    assert manager._toggle_action.text() == "Show ai-manager"
    current = manager._context_menu.actions()
    assert current == actions
    assert [action.text() for action in current] == [
        "Show ai-manager", *snapshot[1:]
    ]


def test_is_available_is_not_cached(mock_tray_available, manager):
    mock_tray_available(False)
    assert manager.is_available() is False

    mock_tray_available(True)
    assert manager.is_available() is True


def test_show_message_delegates_when_available(
    monkeypatch, mock_tray_available, manager
):
    calls = []
    monkeypatch.setattr(
        manager._tray_icon, "showMessage", lambda *args: calls.append(args)
    )

    manager.show_message("Title", "Body")

    assert calls == [
        ("Title", "Body", QSystemTrayIcon.MessageIcon.Information, 5000)
    ]


def test_show_message_is_skipped_when_tray_unavailable(
    monkeypatch, mock_tray_available, manager
):
    calls = []
    mock_tray_available(False)
    monkeypatch.setattr(
        manager._tray_icon, "showMessage", lambda *args: calls.append(args)
    )

    manager.show_message("Title", "Body")

    assert calls == []


def test_show_and_hide_delegate_to_tray_icon(monkeypatch, manager):
    calls = []
    monkeypatch.setattr(manager._tray_icon, "show", lambda: calls.append("show"))
    monkeypatch.setattr(manager._tray_icon, "hide", lambda: calls.append("hide"))

    manager.show()
    manager.hide()

    assert calls == ["show", "hide"]


def test_tray_icon_is_not_null_after_construction(manager):
    assert manager._tray_icon.icon().isNull() is False


def test_palette_changed_reapplies_icon(qapp, monkeypatch, manager):
    calls = []
    monkeypatch.setattr(
        system_tray, "tray_icon", lambda app=None: calls.append(app) or QIcon()
    )

    qapp.paletteChanged.emit(qapp.palette())

    assert len(calls) == 1
