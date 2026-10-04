import json
from pathlib import Path
from typing import Dict, Optional
from PyQt6.QtCore import QThreadPool, QTimer, Qt
from PyQt6.QtGui import QCloseEvent, QColor, QHideEvent, QPalette, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QWidget,
)
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.models import (
    AppAIConfig,
    AppMetadata,
    ModelFetchRequest,
    ModelFetchResponse,
    ServiceRunState,
    ServiceStatus,
    SupervisorStatus,
    ThemeMode,
    UserSettings,
)
from ai_manager.config.yaml_manager import read_app_config, write_app_config
from ai_manager.services.desktop_integration import DesktopIntegrationService
from ai_manager.services.model_fetcher import ModelFetchWorker
from ai_manager.services.supervisor import SupervisorManager
from ai_manager.ui.app_detail_view import AppDetailView
from ai_manager.ui.app_sidebar import AppSidebar
from ai_manager.ui.settings_dialog import SettingsDialog
from ai_manager.ui.system_tray import SystemTrayManager
from ai_manager.ui.theme import get_stylesheet
from ai_manager.utils.path_locator import find_ai_workspace_root


def get_settings_file_path() -> Path:
    config_dir = Path.home() / ".config" / "ai-manager"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "settings.json"


def load_user_settings() -> UserSettings:
    p = get_settings_file_path()
    if p.is_file():
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                return UserSettings(**data)
        except Exception:
            pass
    return UserSettings()


def save_user_settings(settings: UserSettings) -> None:
    p = get_settings_file_path()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(settings.model_dump(), f, indent=2)
    except Exception:
        pass


class MainWindow(QMainWindow):
    """Main window orchestrating sidebar, views, polling and supervisor."""

    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        parent: Optional[QWidget] = None,
        start_minimized_override: bool = False,
    ):
        super().__init__(parent)
        self.workspace_root = workspace_root or find_ai_workspace_root()
        self.apps = get_managed_apps(self.workspace_root)
        self.settings = load_user_settings()

        # State storage
        self._saved_configs: Dict[str, AppAIConfig] = {}
        self._draft_configs: Dict[str, AppAIConfig] = {}
        self._force_quit = False

        self.thread_pool = QThreadPool.globalInstance()
        self.supervisor_manager = SupervisorManager(self.workspace_root, self)
        self.supervisor_manager.status_updated.connect(self._on_supervisor_status)
        self.supervisor_manager.action_completed.connect(self._on_supervisor_action)

        # Desktop integration + system tray
        self.desktop_service = DesktopIntegrationService(self.workspace_root)
        self.tray_manager = SystemTrayManager(self)
        self.tray_manager.toggle_window_requested.connect(self.toggle_window_visibility)
        self.tray_manager.start_all_services_requested.connect(
            self.supervisor_manager.start_supervisor
        )
        self.tray_manager.stop_all_services_requested.connect(
            self.supervisor_manager.stop_supervisor
        )
        self.tray_manager.open_settings_requested.connect(self.open_settings_dialog)
        self.tray_manager.quit_requested.connect(self.handle_quit)
        if self.tray_manager.is_available():
            self.tray_manager.show()
        self.tray_manager.update_visibility_action_text(self.isVisible())

        # Runtime-only override; never persisted to settings.json.
        self.is_minimized_at_startup = bool(
            self.settings.start_minimized or start_minimized_override
        )

        self._init_ui()
        self._load_all_configs()
        self._apply_theme(self.settings.theme)

        # Polling Timer
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.supervisor_manager.refresh_status)
        self._poll_timer.start(self.settings.poll_interval_ms)

        # Initial refresh
        self.supervisor_manager.refresh_status()

    def _init_ui(self) -> None:
        self.setWindowTitle("ai-manager — AI Provider Configuration & Service Controller")
        self.resize(1000, 680)

        # Toolbar
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addWidget(QLabel("Supervisor: ", self))
        self._supervisor_label = QLabel("Checking...", self)
        self._supervisor_label.setStyleSheet("font-weight: 600; color: #9ca3af;")
        toolbar.addWidget(self._supervisor_label)

        self._supervisor_action_btn = QToolButton(self)
        self._supervisor_action_btn.setText("Restart Supervisor")
        self._supervisor_action_btn.clicked.connect(self._on_supervisor_btn_clicked)
        toolbar.addWidget(self._supervisor_action_btn)

        toolbar.addSeparator()

        refresh_btn = QToolButton(self)
        refresh_btn.setText("🔄 Refresh Status (F5)")
        refresh_btn.setShortcut("F5")
        refresh_btn.clicked.connect(self.supervisor_manager.refresh_status)
        toolbar.addWidget(refresh_btn)

        # Spacer
        spacer = QWidget(self)
        spacer.setSizePolicy(
            QWidget.sizePolicy(self).Policy.Expanding,
            QWidget.sizePolicy(self).Policy.Preferred,
        )
        toolbar.addWidget(spacer)

        # Theme toggle
        self._theme_btn = QToolButton(self)
        self._theme_btn.setText("🌙 Dark" if self.settings.theme == ThemeMode.DARK else "☀️ Light")
        self._theme_btn.clicked.connect(self._toggle_theme)
        toolbar.addWidget(self._theme_btn)

        # Settings
        self._settings_btn = QToolButton(self)
        self._settings_btn.setText("⚙ Settings")
        self._settings_btn.clicked.connect(self.open_settings_dialog)
        toolbar.addWidget(self._settings_btn)

        # Central Widget & Splitter
        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal, central)

        # Left Sidebar
        self.sidebar = AppSidebar(self.apps, splitter)
        self.sidebar.app_selected.connect(self._on_app_selected)
        splitter.addWidget(self.sidebar)

        # Right Stacked Detail Views
        self.stack = QStackedWidget(splitter)
        self.views: Dict[str, AppDetailView] = {}

        for app_id, meta in self.apps.items():
            view = AppDetailView(meta, self.stack)
            view.config_changed.connect(self._on_config_changed)
            view.save_requested.connect(self._on_save_requested)
            view.restart_requested.connect(self._on_restart_requested)
            view.fetch_models_requested.connect(self._on_fetch_models)
            self.views[app_id] = view
            self.stack.addWidget(view)

        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 740])
        central_layout.addWidget(splitter)

    def _load_all_configs(self) -> None:
        for app_id, meta in self.apps.items():
            try:
                cfg = read_app_config(meta)
            except Exception:
                cfg = AppAIConfig()
            self._saved_configs[app_id] = cfg
            self._draft_configs[app_id] = cfg.model_copy()
            if app_id in self.views:
                self.views[app_id].load_config(cfg)

    def _on_app_selected(self, app_id: str) -> None:
        if app_id in self.views:
            self.stack.setCurrentWidget(self.views[app_id])

    def _on_config_changed(self, app_id: str, new_draft: AppAIConfig) -> None:
        self._draft_configs[app_id] = new_draft
        is_dirty = new_draft != self._saved_configs.get(app_id)
        self.sidebar.set_dirty(app_id, is_dirty)

    def _on_save_requested(self, app_id: str, config: AppAIConfig, should_restart: bool) -> None:
        meta = self.apps[app_id]
        try:
            write_app_config(meta, config)
            self._saved_configs[app_id] = config.model_copy()
            self._draft_configs[app_id] = config.model_copy()
            self.sidebar.set_dirty(app_id, False)

            if should_restart:
                self.supervisor_manager.restart_service(app_id)
                QMessageBox.information(
                    self,
                    "Saved & Restarted",
                    f"Configuration for {app_id} saved. Sent restart command to supervisor.",
                )
            else:
                QMessageBox.information(
                    self,
                    "Config Saved",
                    f"Configuration for {app_id} saved successfully.",
                )
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save configuration:\n{e}")

    def _on_restart_requested(self, app_id: str) -> None:
        self.supervisor_manager.restart_service(app_id)

    def _on_fetch_models(self, request: ModelFetchRequest) -> None:
        worker = ModelFetchWorker(request)
        worker.signals.finished.connect(self._on_models_fetched)
        self.thread_pool.start(worker)

    def _on_models_fetched(self, response: ModelFetchResponse) -> None:
        # Route response to active view
        current_app = self.sidebar.current_app_id()
        if current_app and current_app in self.views:
            self.views[current_app].on_model_fetch_response(response)

    def _on_supervisor_status(self, status: SupervisorStatus) -> None:
        if status.is_running:
            self._supervisor_label.setText(f"Running (PID {status.supervisor_pid})")
            self._supervisor_label.setStyleSheet("font-weight: 600; color: #10b981;")
            self._supervisor_action_btn.setText("Restart Supervisor")
        else:
            self._supervisor_label.setText("Stopped / Inactive")
            self._supervisor_label.setStyleSheet("font-weight: 600; color: #ef4444;")
            self._supervisor_action_btn.setText("Start Supervisor")

        # Update per-app views & sidebar
        for app_id, s_stat in status.services.items():
            if app_id in self.apps:
                self.sidebar.update_status(app_id, s_stat)
                if app_id in self.views:
                    self.views[app_id].update_service_status(s_stat)

    def _on_supervisor_btn_clicked(self) -> None:
        if self._supervisor_action_btn.text() == "Start Supervisor":
            self.supervisor_manager.start_supervisor()
        else:
            self.supervisor_manager.start_supervisor()

    def _on_supervisor_action(self, action: str, success: bool, msg: str) -> None:
        if not success:
            QMessageBox.warning(self, "Supervisor Action Failed", f"Action: {action}\n{msg}")

    def _toggle_theme(self) -> None:
        new_theme = ThemeMode.LIGHT if self.settings.theme == ThemeMode.DARK else ThemeMode.DARK
        self._apply_theme(new_theme)

    def _apply_theme(self, theme: ThemeMode) -> None:
        self.settings.theme = theme
        save_user_settings(self.settings)
        qapp = QApplication.instance()
        if qapp:
            qapp.setStyleSheet(get_stylesheet(theme))
            palette = QPalette()
            if theme == ThemeMode.DARK:
                palette.setColor(QPalette.ColorRole.Window, QColor("#18181f"))
                palette.setColor(QPalette.ColorRole.WindowText, QColor("#e2e8f0"))
                palette.setColor(QPalette.ColorRole.Base, QColor("#121217"))
                palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1b1b22"))
                palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#20202a"))
                palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f3f4f6"))
                palette.setColor(QPalette.ColorRole.Text, QColor("#e2e8f0"))
                palette.setColor(QPalette.ColorRole.Button, QColor("#262633"))
                palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e2e8f0"))
                palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
                palette.setColor(QPalette.ColorRole.Highlight, QColor("#2563eb"))
                palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            else:
                palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
                palette.setColor(QPalette.ColorRole.WindowText, QColor("#1e293b"))
                palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
                palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f1f5f9"))
                palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
                palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#0f172a"))
                palette.setColor(QPalette.ColorRole.Text, QColor("#0f172a"))
                palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
                palette.setColor(QPalette.ColorRole.ButtonText, QColor("#334155"))
                palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
                palette.setColor(QPalette.ColorRole.Highlight, QColor("#2563eb"))
                palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            qapp.setPalette(palette)
        self._theme_btn.setText("🌙 Dark" if theme == ThemeMode.DARK else "☀️ Light")

    def toggle_window_visibility(self) -> None:
        """Show/activate the window, or hide it when it is already focused."""
        if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
            self.hide()
        else:
            # Unminimize and activate reliably on KDE Plasma / Wayland / X11
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def open_settings_dialog(self) -> None:
        """Open the modal application settings dialog."""
        dialog = SettingsDialog(self.settings, self.desktop_service, parent=self)
        dialog.settings_saved.connect(self._on_settings_saved)
        dialog.exec()

    def _on_settings_saved(self, new_settings: UserSettings) -> None:
        """Apply settings live and persist them once."""
        self.settings = new_settings
        save_user_settings(self.settings)
        self._poll_timer.setInterval(new_settings.poll_interval_ms)
        # _apply_theme also persists, which is harmless and idempotent.
        self._apply_theme(new_settings.theme)

    def _exit_application(self) -> None:
        """Terminate the process even though quit-on-last-window is disabled."""
        self._force_quit = True
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def handle_quit(self) -> None:
        """Quit the application, guarding against unsaved drafts."""
        if self.has_unsaved_changes():
            self.showNormal()
            self.raise_()
            self.activateWindow()
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Discard and exit?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Discard:
                return
        # Set force_quit before closing so closeEvent accepts even when
        # close-to-tray would otherwise intercept an explicit quit.
        self._force_quit = True
        self.close()
        self._exit_application()

    def has_unsaved_changes(self) -> bool:
        for app_id, saved in self._saved_configs.items():
            draft = self._draft_configs.get(app_id)
            if draft and draft != saved:
                return True
        return False

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._force_quit:
            # Invariant: every setter of _force_quit (handle_quit,
            # _exit_application) also terminates the application, so accepting
            # here never orphans the process under quitOnLastWindowClosed(False).
            event.accept()
            return

        if self.settings.close_to_tray and self.tray_manager.is_available():
            event.ignore()
            self.hide()
            if not self.settings.first_close_notice_shown:
                self.tray_manager.show_message(
                    "ai-manager running in tray",
                    "The application will keep supervising services in the background.\n"
                    "Click the tray icon to restore or quit.",
                )
                self.settings.first_close_notice_shown = True
                save_user_settings(self.settings)
            return

        if self.has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved configuration changes. Discard and exit?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Discard:
                event.ignore()
                return
        event.accept()
        # quitOnLastWindowClosed is disabled, so accepting the close is not
        # enough on its own: explicitly terminate the application.
        self._exit_application()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.tray_manager.update_visibility_action_text(True)

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self.tray_manager.update_visibility_action_text(False)
