"""Unit tests for the SettingsDialog component.

These tests run headless (``QT_QPA_PLATFORM=offscreen``) and use a fake
``DesktopIntegrationService`` so the real ``~/.config`` and ``~/.local``
directories are never touched.
"""

import pytest

from unittest.mock import MagicMock, call

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QPushButton,
)

from ai_manager.config.models import ThemeMode, UserSettings
from ai_manager.ui import settings_dialog as settings_dialog_module
from ai_manager.ui.about_dialog import AboutDialog
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


def test_cmb_poll_attribute_alias(dialog):
    # Spec §5.2 names the widget cmb_poll while the implementation uses the
    # more explicit cmb_poll_interval; both names must resolve.
    assert dialog.cmb_poll is dialog.cmb_poll_interval


def test_tray_unavailable_notice_shown_when_tray_missing(
    qtbot, settings, service, mock_tray_available
):
    mock_tray_available(False)
    dlg = SettingsDialog(settings, service)
    qtbot.addWidget(dlg)

    assert dlg.lbl_tray_unavailable.isHidden() is False


def test_tray_unavailable_notice_hidden_when_tray_available(
    qtbot, settings, service, mock_tray_available
):
    dlg = SettingsDialog(settings, service)
    qtbot.addWidget(dlg)

    assert dlg.lbl_tray_unavailable.isHidden() is True


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


def _about_snapshot(settings, dlg, service):
    return (
        settings.model_dump(),
        dlg.settings.model_dump(),
        (
            dlg.chk_close_to_tray.isChecked(),
            dlg.chk_start_minimized.isChecked(),
            dlg.chk_autostart.isChecked(),
            dlg.cmb_theme.currentData(),
            dlg.cmb_poll_interval.currentData(),
        ),
        list(service.autostart_calls),
        service.install_calls,
        service.remove_calls,
    )


def test_about_button_sits_left_of_action_buttons(dialog):
    assert isinstance(dialog.btn_about, QPushButton)
    assert dialog.btn_about.text() == "About ai-manager"
    assert dialog.btn_about.parentWidget() is dialog
    boxes = dialog.findChildren(QDialogButtonBox)
    assert len(boxes) == 1
    box = boxes[0]
    assert dialog.btn_about not in box.buttons()
    assert box.orientation() == Qt.Orientation.Horizontal
    assert box.standardButtons() == (
        QDialogButtonBox.StandardButton.Save
        | QDialogButtonBox.StandardButton.Cancel
    )
    assert box.button(QDialogButtonBox.StandardButton.Save) is dialog.btn_save
    assert box.button(QDialogButtonBox.StandardButton.Cancel) is dialog.btn_cancel
    assert dialog.btn_save.text() == "Save && Apply"
    assert dialog.btn_cancel.text() == "Cancel"
    assert set(box.buttons()) == {dialog.btn_save, dialog.btn_cancel}
    outer = dialog.layout()
    footer = outer.itemAt(outer.count() - 1).layout()
    assert isinstance(footer, QHBoxLayout)
    assert footer.count() == 3
    assert footer.itemAt(0).widget() is dialog.btn_about
    spacer = footer.itemAt(1).spacerItem()
    assert spacer is not None
    assert spacer.expandingDirections() & Qt.Orientation.Horizontal
    assert footer.stretch(1) == 1
    assert footer.itemAt(2).widget() is box
    dialog.show()
    outer.activate()
    footer.activate()
    box.layout().activate()
    QApplication.processEvents()
    about_right = (
        dialog.btn_about.mapTo(dialog, QPoint(0, 0)).x()
        + dialog.btn_about.width()
    )
    for btn_x in (dialog.btn_save, dialog.btn_cancel):
        assert about_right <= btn_x.mapTo(dialog, QPoint(0, 0)).x()


@pytest.mark.parametrize("tray_available", [True, False])
def test_about_button_opens_about_without_saving(
    qtbot, settings, service, monkeypatch, mock_tray_available, tray_available
):
    mock_tray_available(tray_available)
    dlg = SettingsDialog(settings, service)
    qtbot.addWidget(dlg)
    dlg.chk_autostart.setChecked(True)
    before = _about_snapshot(settings, dlg, service)
    saved, accepted, rejected = [], [], []
    dlg.settings_saved.connect(saved.append)
    dlg.accepted.connect(lambda: accepted.append(True))
    dlg.rejected.connect(lambda: rejected.append(True))
    instance = MagicMock()
    factory = MagicMock(return_value=instance)
    monkeypatch.setattr(settings_dialog_module, "AboutDialog", factory)

    dlg.btn_about.click()

    factory.assert_called_once_with(parent=dlg)
    instance.exec.assert_called_once_with()
    assert saved == []
    assert accepted == []
    assert rejected == []
    assert _about_snapshot(settings, dlg, service) == before
    assert dlg.chk_autostart.isChecked() is True


def test_about_button_constructs_fresh_dialog_each_time(dialog, monkeypatch):
    saved = []
    dialog.settings_saved.connect(saved.append)
    first, second = MagicMock(), MagicMock()
    factory = MagicMock(side_effect=[first, second])
    monkeypatch.setattr(settings_dialog_module, "AboutDialog", factory)

    dialog.btn_about.click()
    dialog.btn_about.click()

    assert factory.call_args_list == [call(parent=dialog), call(parent=dialog)]
    first.exec.assert_called_once_with()
    second.exec.assert_called_once_with()
    assert saved == []


def test_about_click_uses_real_dialog_parented_to_settings(
    qtbot, settings, service, dialog, monkeypatch
):
    dlg = dialog
    dlg.chk_autostart.setChecked(True)
    before = _about_snapshot(settings, dlg, service)
    saved, accepted, rejected = [], [], []
    dlg.settings_saved.connect(saved.append)
    dlg.accepted.connect(lambda: accepted.append(True))
    dlg.rejected.connect(lambda: rejected.append(True))
    instances = []

    def recorder(self):
        qtbot.addWidget(self)
        instances.append((self, self.parentWidget()))
        return 1

    monkeypatch.setattr(AboutDialog, "exec", recorder)
    observed = []

    def click_and_capture():
        try:
            dlg.btn_about.click()
            observed.append((
                dlg.isVisible(),
                dlg.isModal(),
                dlg.result(),
                _about_snapshot(settings, dlg, service),
                list(saved),
                list(accepted),
                list(rejected),
                dlg.chk_autostart.isChecked(),
            ))
        finally:
            dlg.reject()

    dlg.show()
    QTimer.singleShot(0, click_and_capture)
    assert dlg.exec() == QDialog.DialogCode.Rejected

    assert len(instances) == 1
    about, supplied_parent = instances[0]
    assert isinstance(about, AboutDialog)
    assert supplied_parent is dlg
    assert about.parentWidget() is dlg
    assert about.isModal() is True
    assert observed == [(
        True, True, QDialog.DialogCode.Rejected, before, [], [], [], True
    )]
    assert saved == []
    assert accepted == []
