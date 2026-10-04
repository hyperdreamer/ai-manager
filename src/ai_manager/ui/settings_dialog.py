"""Application settings dialog for ai-manager.

``SettingsDialog`` is a modal :class:`QDialog` that consolidates system
integration toggles, desktop shortcut management and general preferences.

It edits a copy of :class:`~ai_manager.config.models.UserSettings` and only
publishes the updated value through :attr:`settings_saved` when the user
clicks *Save & Apply*. This guarantees the caller's settings object and the
persisted ``settings.json`` are never mutated by transient dialog edits.
"""

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ai_manager.config.models import ThemeMode, UserSettings
from ai_manager.services.desktop_integration import DesktopIntegrationService

# Poll intervals offered in the General Preferences section.
POLL_INTERVAL_OPTIONS = (2000, 4000, 6000, 10000)


class SettingsDialog(QDialog):
    """Modal settings editor for system integration and app preferences."""

    settings_saved = pyqtSignal(UserSettings)

    def __init__(
        self,
        settings: UserSettings,
        desktop_service: DesktopIntegrationService,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.settings = settings.model_copy()
        self.desktop_service = desktop_service
        self.setWindowTitle("Application Settings")
        self.setModal(True)
        self._init_ui()
        self._load_from_settings()
        self._refresh_desktop_status()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        layout.addWidget(self._build_system_group())
        layout.addWidget(self._build_desktop_group())
        layout.addWidget(self._build_general_group())
        layout.addStretch(1)
        layout.addWidget(self._build_button_box())

    def _build_system_group(self) -> QGroupBox:
        group = QGroupBox("System Integration", self)
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)

        self.chk_close_to_tray = QCheckBox(
            "Minimize to system tray when closing window [X]", group
        )
        self.chk_start_minimized = QCheckBox(
            "Start minimized to system tray", group
        )
        self.chk_autostart = QCheckBox(
            "Run on system startup (Autostart)", group
        )

        hint = QLabel("Creates ~/.config/autostart/ai-manager.desktop", group)
        hint.setObjectName("formSectionMuted")
        hint.setIndent(26)

        self.lbl_tray_unavailable = QLabel(
            "System tray is unavailable on this display server; closing the "
            "window will exit the application instead of minimizing to tray.",
            group,
        )
        self.lbl_tray_unavailable.setObjectName("formSectionMuted")
        self.lbl_tray_unavailable.setWordWrap(True)
        self.lbl_tray_unavailable.setVisible(not QSystemTrayIcon.isSystemTrayAvailable())

        group_layout.addWidget(self.chk_close_to_tray)
        group_layout.addWidget(self.chk_start_minimized)
        group_layout.addWidget(self.chk_autostart)
        group_layout.addWidget(hint)
        group_layout.addWidget(self.lbl_tray_unavailable)
        return group

    def _build_desktop_group(self) -> QGroupBox:
        # "&&" renders a literal ampersand; a single "&" would be swallowed
        # as a mnemonic marker and the title would read "Desktop _Application Menu".
        group = QGroupBox("Desktop && Application Menu", self)
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(10)

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Start Menu Status:", group))
        self.lbl_desktop_status = QLabel(group)
        status_row.addWidget(self.lbl_desktop_status)
        status_row.addStretch(1)
        group_layout.addLayout(status_row)

        button_row = QHBoxLayout()
        self.btn_install_desktop = QPushButton("Install / Update Shortcut", group)
        self.btn_remove_desktop = QPushButton("Remove Shortcut", group)
        button_row.addWidget(self.btn_install_desktop)
        button_row.addWidget(self.btn_remove_desktop)
        button_row.addStretch(1)
        group_layout.addLayout(button_row)

        self.btn_install_desktop.clicked.connect(self._on_install_desktop)
        self.btn_remove_desktop.clicked.connect(self._on_remove_desktop)
        return group

    def _build_general_group(self) -> QGroupBox:
        group = QGroupBox("General Preferences", self)
        form = QFormLayout(group)
        form.setSpacing(10)

        self.cmb_theme = QComboBox(group)
        self.cmb_theme.addItem("Dark", ThemeMode.DARK)
        self.cmb_theme.addItem("Light", ThemeMode.LIGHT)

        self.cmb_poll_interval = QComboBox(group)
        for interval in POLL_INTERVAL_OPTIONS:
            self.cmb_poll_interval.addItem(f"{interval} ms", interval)
        # Spec §5.2 refers to this widget as ``cmb_poll``; expose both names.
        self.cmb_poll = self.cmb_poll_interval

        form.addRow("Theme:", self.cmb_theme)
        form.addRow("Polling Interval:", self.cmb_poll_interval)
        return group

    def _build_button_box(self) -> QDialogButtonBox:
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        self.btn_save = button_box.button(QDialogButtonBox.StandardButton.Save)
        # "&&" renders a literal ampersand; a single "&" is swallowed as a
        # mnemonic marker and the button would read "Save _Apply".
        self.btn_save.setText("Save && Apply")
        self.btn_cancel = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        self.btn_cancel.setText("Cancel")

        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self.reject)
        return button_box

    # ------------------------------------------------------------------
    # State synchronisation
    # ------------------------------------------------------------------
    def _load_from_settings(self) -> None:
        """Initialise every widget from the copied settings object."""
        self.chk_close_to_tray.setChecked(self.settings.close_to_tray)
        self.chk_start_minimized.setChecked(self.settings.start_minimized)
        self.chk_autostart.setChecked(self.settings.autostart)

        theme_index = self.cmb_theme.findData(self.settings.theme)
        if theme_index >= 0:
            self.cmb_theme.setCurrentIndex(theme_index)

        poll_index = self.cmb_poll_interval.findData(self.settings.poll_interval_ms)
        if poll_index < 0:
            # Preserve a persisted interval that is not one of the presets.
            self.cmb_poll_interval.addItem(
                f"{self.settings.poll_interval_ms} ms", self.settings.poll_interval_ms
            )
            poll_index = self.cmb_poll_interval.count() - 1
        self.cmb_poll_interval.setCurrentIndex(poll_index)

    def _refresh_desktop_status(self) -> None:
        """Update the status badge from the desktop service."""
        installed = bool(self.desktop_service.is_desktop_shortcut_installed())
        if installed:
            self.lbl_desktop_status.setText("Installed in Application Menu")
            self.lbl_desktop_status.setObjectName("statusBadgeRunning")
        else:
            self.lbl_desktop_status.setText("Not installed")
            self.lbl_desktop_status.setObjectName("statusBadgeStopped")
        self.lbl_desktop_status.style().unpolish(self.lbl_desktop_status)
        self.lbl_desktop_status.style().polish(self.lbl_desktop_status)

    def _build_settings(self) -> UserSettings:
        """Read widget state back into a fresh ``UserSettings`` instance."""
        new_settings = self.settings.model_copy()
        new_settings.close_to_tray = self.chk_close_to_tray.isChecked()
        new_settings.start_minimized = self.chk_start_minimized.isChecked()
        new_settings.autostart = self.chk_autostart.isChecked()
        new_settings.theme = self.cmb_theme.currentData()
        new_settings.poll_interval_ms = self.cmb_poll_interval.currentData()
        return new_settings

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_install_desktop(self) -> None:
        self.desktop_service.install_desktop_shortcut()
        self._refresh_desktop_status()

    def _on_remove_desktop(self) -> None:
        self.desktop_service.remove_desktop_shortcut()
        self._refresh_desktop_status()

    def _on_save(self) -> None:
        new_settings = self._build_settings()
        self.settings = new_settings
        self.desktop_service.set_autostart(
            new_settings.autostart,
            start_minimized=new_settings.start_minimized,
        )
        self.settings_saved.emit(new_settings)
        self.accept()
