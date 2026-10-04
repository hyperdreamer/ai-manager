"""Unit tests for the SettingsDialog component.

These tests run headless (``QT_QPA_PLATFORM=offscreen``) and use a fake
``DesktopIntegrationService`` so the real ``~/.config`` and ``~/.local``
directories are never touched.
"""

import pytest

from ai_manager.config.models import ThemeMode, UserSettings
from ai_manager.ui.settings_dialog import SettingsDialog


class FakeDesktopService:
    """Minimal stand-in recording service interactions."""

    def __init__(self, installed: bool = False):
        self._installed = installed
        self.autostart_calls = []
        self.install_calls = 0
        self.remove_calls = 0

    def is_desktop_shortcut_installed(self) -> bool:
        return self._installed

    def install_desktop_shortcut(self) -> bool:
        self.install_calls += 1
        self._installed = True
        return True

    def remove_desktop_shortcut(self) -> bool:
        self.remove_calls += 1
        self._installed = False
        return True

    def set_autostart(self, enabled: bool, start_minimized: bool = False) -> bool:
        self.autostart_calls.append((enabled, start_minimized))
        return True


@pytest.fixture
def settings():
    return UserSettings(
        theme=ThemeMode.LIGHT,
        poll_interval_ms=6000,
        close_to_tray=False,
        start_minimized=True,
        autostart=False,
        first_close_notice_shown=False,
    )


@pytest.fixture
def service():
    return FakeDesktopService(installed=True)


@pytest.fixture
def dialog(qtbot, settings, service):
    dlg = SettingsDialog(settings, service)
    qtbot.addWidget(dlg)
    return dlg


def test_initial_control_states_reflect_settings(dialog):
    assert dialog.chk_close_to_tray.isChecked() is False
    assert dialog.chk_start_minimized.isChecked() is True
    assert dialog.chk_autostart.isChecked() is False
    assert dialog.cmb_theme.currentData() == ThemeMode.LIGHT
    assert dialog.cmb_poll_interval.currentData() == 6000
    assert dialog.lbl_desktop_status.text() == "Installed in Application Menu"


def test_dialog_copies_settings_without_mutating_caller(qtbot, settings, service):
    dlg = SettingsDialog(settings, service)
    qtbot.addWidget(dlg)

    dlg.chk_autostart.setChecked(True)
    dlg.chk_close_to_tray.setChecked(True)

    # Caller's settings object must be untouched until Save & Apply.
    assert settings.autostart is False
    assert settings.close_to_tray is False
    assert dlg.settings is not settings


def test_save_emits_settings_and_syncs_autostart(qtbot, settings, service):
    dlg = SettingsDialog(settings, service)
    qtbot.addWidget(dlg)

    dlg.chk_autostart.setChecked(True)
    dlg.chk_start_minimized.setChecked(True)

    with qtbot.waitSignal(dlg.settings_saved, timeout=1000) as blocker:
        dlg.btn_save.click()

    emitted = blocker.args[0]
    assert isinstance(emitted, UserSettings)
    assert emitted.autostart is True
    assert emitted.start_minimized is True
    assert service.autostart_calls == [(True, True)]
    assert dlg.result() == 1  # QDialog.DialogCode.Accepted


def test_save_without_autostart_disables_it(qtbot, settings, service):
    dlg = SettingsDialog(settings, service)
    qtbot.addWidget(dlg)

    with qtbot.waitSignal(dlg.settings_saved, timeout=1000) as blocker:
        dlg.btn_save.click()

    assert blocker.args[0].autostart is False
    assert service.autostart_calls == [(False, True)]


def test_install_button_calls_service_and_updates_badge(qtbot, settings):
    svc = FakeDesktopService(installed=False)
    dlg = SettingsDialog(settings, svc)
    qtbot.addWidget(dlg)

    assert dlg.lbl_desktop_status.text() == "Not installed"

    dlg.btn_install_desktop.click()

    assert svc.install_calls == 1
    assert dlg.lbl_desktop_status.text() == "Installed in Application Menu"


def test_remove_button_calls_service_and_updates_badge(qtbot, settings, service):
    dlg = SettingsDialog(settings, service)
    qtbot.addWidget(dlg)

    assert dlg.lbl_desktop_status.text() == "Installed in Application Menu"

    dlg.btn_remove_desktop.click()

    assert service.remove_calls == 1
    assert dlg.lbl_desktop_status.text() == "Not installed"


def test_theme_and_poll_interval_are_read_back(qtbot, settings, service):
    dlg = SettingsDialog(settings, service)
    qtbot.addWidget(dlg)

    dlg.cmb_theme.setCurrentIndex(dlg.cmb_theme.findData(ThemeMode.DARK))
    dlg.cmb_poll_interval.setCurrentIndex(dlg.cmb_poll_interval.findData(10000))

    with qtbot.waitSignal(dlg.settings_saved, timeout=1000) as blocker:
        dlg.btn_save.click()

    emitted = blocker.args[0]
    assert emitted.theme == ThemeMode.DARK
    assert emitted.poll_interval_ms == 10000


def test_theme_combo_options(dialog):
    values = [dialog.cmb_theme.itemData(i) for i in range(dialog.cmb_theme.count())]
    assert values == [ThemeMode.DARK, ThemeMode.LIGHT]


def test_poll_interval_combo_options(dialog):
    values = [
        dialog.cmb_poll_interval.itemData(i)
        for i in range(dialog.cmb_poll_interval.count())
    ]
    assert values == [2000, 4000, 6000, 10000]


def test_cancel_rejects_without_saving(qtbot, settings, service):
    dlg = SettingsDialog(settings, service)
    qtbot.addWidget(dlg)

    dlg.chk_autostart.setChecked(True)
    dlg.btn_cancel.click()

    assert dlg.result() == 0  # QDialog.DialogCode.Rejected
    assert service.autostart_calls == []
