import json
from pathlib import Path
from typing import Dict, Optional
from PyQt6.QtCore import QThreadPool, QTimer, Qt
from PyQt6.QtGui import QCloseEvent
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
from ai_manager.services.model_fetcher import ModelFetchWorker
from ai_manager.services.supervisor import SupervisorManager
from ai_manager.ui.app_detail_view import AppDetailView
from ai_manager.ui.app_sidebar import AppSidebar
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

    def __init__(self, workspace_root: Optional[Path] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.workspace_root = workspace_root or find_ai_workspace_root()
        self.apps = get_managed_apps(self.workspace_root)
        self.settings = load_user_settings()

        # State storage
        self._saved_configs: Dict[str, AppAIConfig] = {}
        self._draft_configs: Dict[str, AppAIConfig] = {}

        self.thread_pool = QThreadPool.globalInstance()
        self.supervisor_manager = SupervisorManager(self.workspace_root, self)
        self.supervisor_manager.status_updated.connect(self._on_supervisor_status)
        self.supervisor_manager.action_completed.connect(self._on_supervisor_action)

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
        self._theme_btn.setText("🌙 Dark" if theme == ThemeMode.DARK else "☀️ Light")

    def has_unsaved_changes(self) -> bool:
        for app_id, saved in self._saved_configs.items():
            draft = self._draft_configs.get(app_id)
            if draft and draft != saved:
                return True
        return False

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved configuration changes. Discard and exit?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
