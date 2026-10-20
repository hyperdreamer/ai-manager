import copy
import json
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Dict, Optional
from PyQt6.QtCore import QThreadPool, QTimer, Qt, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QColor, QHideEvent, QPalette, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
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
from ai_manager.config.blast_radius import (
    auth_mismatch_warning,
    endpoint,
    find_affected_dependents,
    urls_match,
)
from ai_manager.config.config_errors import (
    ConfigError,
    ConfigLoadError,
    ConfigValidationError,
    ReadOnlyConfigError,
    ServiceValidationError,
    ServiceValidationTimeout,
    StaleDocumentError,
    TransactionError,
    UnknownConfigKindError,
)
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
from ai_manager.config.structured_config import _candidate, load as load_structured, render
from ai_manager.config.structured_models import LauncherProbeResult, SaveResult, StructuredDoc
from ai_manager.config.structured_schema import validate_in_process
from ai_manager.config.yaml_manager import read_app_config, write_app_config
from ai_manager.services.config_jobs import LauncherProbeJob, StructuredSaveJob
from ai_manager.services.desktop_integration import DesktopIntegrationService
from ai_manager.services.model_fetcher import ModelFetchWorker
from ai_manager.services.supervisor import SupervisorManager
from ai_manager.ui.app_detail_view import AppDetailView
from ai_manager.ui.app_sidebar import AppSidebar
from ai_manager.ui.config_dialogs import (
    BlastRadiusDialog,
    ReviewChangesDialog,
    StaleDocumentDialog,
    TransactionReportDialog,
)
from ai_manager.ui.settings_dialog import SettingsDialog
from ai_manager.ui.structured_config_view import StructuredConfigView
from ai_manager.ui.system_tray import SystemTrayManager
from ai_manager.ui.theme import get_stylesheet
from ai_manager.utils.path_locator import find_ai_workspace_root


# Refusal shown whenever a payload does not match the app's config kind.
PAYLOAD_KIND_MISMATCH = (
    "Configuration draft does not match this app's config kind; save refused."
)


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

        # State storage. Saved/draft payloads are typed by config kind: an
        # ``AppAIConfig`` for LLM apps and a ``StructuredDoc`` otherwise.
        self._saved_configs: Dict[str, object] = {}
        self._draft_configs: Dict[str, object] = {}
        self._launcher_gate_cache: Dict[Path, Optional[LauncherProbeResult]] = {}
        self._probe_jobs: Dict[Path, LauncherProbeJob] = {}
        self._save_jobs: Dict[str, StructuredSaveJob] = {}
        self._model_workers: Dict[int, ModelFetchWorker] = {}
        self._pending_restarts: Dict[str, bool] = {}
        self._save_restart_pending: set[str] = set()
        self._submitting_restart: Optional[str] = None
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
        self._start_launcher_probes()
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
        self.views: Dict[str, AppDetailView | StructuredConfigView] = {}

        for app_id, meta in self.apps.items():
            # Exhaustive dispatch: every registered kind gets its adapter and an
            # unknown kind can never fall through to a silent default.
            if meta.config_kind == "llm":
                view = AppDetailView(meta, self.stack)
            elif meta.config_kind in ("chat2api", "file-bridge"):
                view = StructuredConfigView(meta, self.stack)
            else:
                raise UnknownConfigKindError(meta.config_kind)
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
        for app_id in self.apps:
            self._load_config(app_id)
        self._update_auth_warnings()

    def _load_config(self, app_id: str) -> None:
        meta, view = self.apps[app_id], self.views[app_id]
        if meta.config_kind == "llm":
            try:
                config = read_app_config(meta)
            except Exception:
                config = AppAIConfig()
        elif meta.config_kind in ("chat2api", "file-bridge"):
            try:
                config = load_structured(
                    meta.config_kind, meta.relative_path / meta.config_file_name
                )
            except ConfigLoadError as exc:
                view.show_load_error(
                    exc.detail
                    if exc.reason in ("non-dict-root", "symlink")
                    else str(exc),
                    exc.reason,
                )
                self.sidebar.update_configured_port(app_id, None)
                # A failed reload retains the previous owned draft and dirty state.
                self._set_dirty_indicator(app_id)
                return
        else:
            raise UnknownConfigKindError(meta.config_kind)
        # Everything below derives state from the parsed document. A pathological
        # document can pass shape checks yet still defeat a deep copy or a widget
        # (deep nesting raising RecursionError, for example). Such a failure must
        # leave this app in its disabled load-error state rather than escape, because
        # this runs during MainWindow construction and one bad file must not stop the
        # manager from opening.
        try:
            saved = copy.deepcopy(config)
            draft = copy.deepcopy(config)
        except RecursionError:
            if meta.config_kind in ("chat2api", "file-bridge"):
                view.show_load_error(
                    "Configuration is nested too deeply to edit; save is disabled.",
                    "load-error",
                )
                self.sidebar.update_configured_port(app_id, None)
                self._saved_configs.pop(app_id, None)
                self._draft_configs.pop(app_id, None)
                self._set_dirty_indicator(app_id)
                return
            raise
        self._saved_configs[app_id] = saved
        self._draft_configs[app_id] = draft
        try:
            view.load_config(config)
        except Exception as exc:  # widget rejection must not abort startup
            if meta.config_kind in ("chat2api", "file-bridge"):
                view.show_load_error(
                    f"Configuration could not be displayed: {exc}", "load-error"
                )
                self.sidebar.update_configured_port(app_id, None)
                self._set_dirty_indicator(app_id)
                return
            raise
        self._update_configured_port(app_id, config)
        self._set_dirty_indicator(app_id)

    def _reload_config(self, app_id: str) -> None:
        self._load_config(app_id)
        self._update_auth_warnings()

    def _on_app_selected(self, app_id: str) -> None:
        if app_id in self.views:
            self.stack.setCurrentWidget(self.views[app_id])

    def _update_configured_port(self, app_id: str, config) -> None:
        """Show the effective saved port, falling back to the metadata default."""
        kind = self.apps[app_id].config_kind
        if kind == "llm":
            return
        if kind not in ("chat2api", "file-bridge"):
            raise UnknownConfigKindError(kind)
        if not config.existed:
            self.sidebar.update_configured_port(app_id, None)
            return
        values = config.doc.get("server", {}) if kind == "chat2api" else config.doc
        port = values.get("port", self.apps[app_id].default_port)
        self.sidebar.update_configured_port(
            app_id, port if type(port) is int and 1 <= port <= 65535 else None
        )

    def _is_dirty(self, app_id: str) -> bool:
        saved, draft = self._saved_configs.get(app_id), self._draft_configs.get(app_id)
        kind = self.apps[app_id].config_kind
        if kind == "llm":
            return draft is not None and draft != saved
        if kind not in ("chat2api", "file-bridge"):
            raise UnknownConfigKindError(kind)
        if draft is None:
            return False
        # Saved/draft payloads are ``object``: an LLM app holds an
        # ``AppAIConfig`` and a structured app holds a ``StructuredDoc``. Narrow
        # to the structured records here instead of widening the annotations.
        if not isinstance(draft, StructuredDoc) or not isinstance(saved, StructuredDoc):
            # Without a structured baseline nothing can compare equal.
            return True
        if draft.create_requested:
            return True
        if not draft.existed:
            return False
        if draft.input_issues or draft.raw_option_edits:
            try:
                return render(kind, saved) != render(kind, draft)
            except ConfigError:
                return True
        if draft.read_only_reasons and not draft.mutations:
            return False
        try:
            return render(
                kind, replace(saved, mutations=(), raw_option_edits={}, input_issues=())
            ) != render(kind, draft)
        except ConfigError:
            return bool(draft.mutations) or saved is None

    def _set_dirty_indicator(self, app_id: str) -> None:
        dirty = self._is_dirty(app_id)
        self.sidebar.set_dirty(app_id, dirty)
        view = self.views.get(app_id)
        if view is not None:
            view._dirty_label.setText("Unsaved changes" if dirty else "")

    def _check_payload(self, app_id: str, config: object) -> None:
        meta = self.apps[app_id]
        if meta.config_kind == "llm":
            valid = isinstance(config, AppAIConfig)
        elif meta.config_kind in ("chat2api", "file-bridge"):
            valid = isinstance(config, StructuredDoc) and config.kind == meta.config_kind
        else:
            raise UnknownConfigKindError(meta.config_kind)
        if not valid:
            raise ConfigError(PAYLOAD_KIND_MISMATCH)

    def _on_config_changed(self, app_id: str, new_draft: object) -> None:
        try:
            self._check_payload(app_id, new_draft)
        except ConfigError as exc:
            self.views[app_id].show_config_error(str(exc))
            return
        self._draft_configs[app_id] = copy.deepcopy(new_draft)
        self._set_dirty_indicator(app_id)
        self._update_auth_warnings()

    def _on_save_requested(self, app_id: str, config: object, should_restart: bool) -> None:
        if app_id in self._save_jobs:
            return
        meta, view = self.apps[app_id], self.views[app_id]
        try:
            self._check_payload(app_id, config)
            if meta.config_kind == "llm":
                if not isinstance(config, AppAIConfig):
                    raise ConfigError(PAYLOAD_KIND_MISMATCH)
                write_app_config(meta, config)
                self._saved_configs[app_id] = config.model_copy(deep=True)
                self._draft_configs[app_id] = config.model_copy(deep=True)
                view.adopt_saved_baseline(config, preserve_draft=False)
                self._set_dirty_indicator(app_id)
                self._update_auth_warnings()
                if should_restart:
                    self._request_saved_restart(app_id)
                else:
                    view.show_config_error("Configuration saved.")
                return
            if meta.config_kind not in ("chat2api", "file-bridge"):
                raise UnknownConfigKindError(meta.config_kind)
            if not isinstance(config, StructuredDoc):
                raise ConfigError(PAYLOAD_KIND_MISMATCH)
            if not config.existed and not config.create_requested:
                raise ConfigError("Create a draft from the example before saving.")
            selected = self._resolve_dependents(meta, config)
            if selected is None:
                # The user declined the dependent rewrite: nothing is staged,
                # the draft stays dirty and no restart is requested.
                self._set_dirty_indicator(app_id)
                return
            job = StructuredSaveJob(meta, config, selected)
            self._save_jobs[app_id] = job
            self._pending_restarts[app_id] = bool(should_restart)
            view.set_save_in_progress(True)
            job.signals.save_finished.connect(
                self._on_structured_saved, Qt.ConnectionType.QueuedConnection
            )
            job.signals.save_failed.connect(
                self._on_structured_save_failed, Qt.ConnectionType.QueuedConnection
            )
            self.thread_pool.start(job)
        except ConfigError as exc:
            self._on_structured_save_failed(app_id, exc)
        except Exception as exc:
            self._on_structured_save_failed(
                app_id, ConfigError(f"Configuration save failed: {exc}")
            )

    def _resolve_dependents(self, meta, config):
        """Gate listener changes and return the user-selected dependent set.

        Returns ``None`` when the blast-radius dialog was declined, which is
        distinct from an empty tuple: an empty tuple means "no dependents to
        rewrite" and still commits the primary configuration.
        """
        if meta.config_kind != "chat2api":
            return ()
        previous = self._saved_configs.get(meta.id)

        def listener(document):
            server = _candidate(document).get("server", {})
            return tuple(
                (type(server.get(key, default)), server.get(key, default))
                for key, default in (("host", "127.0.0.1"), ("port", 8000))
            )

        changed = previous is not None and listener(previous) != listener(config)
        gate = self._launcher_gate_cache.get(meta.relative_path.resolve())
        if changed and (gate is None or not gate.passed):
            raise ReadOnlyConfigError(
                config.path,
                "Launcher has not passed the configuration probe; "
                "host/port changes cannot be saved.",
            )
        if not changed:
            return ()
        # The chat2api schema is pure; reject malformed listener values before
        # constructing URLs or opening a blast-radius dialog.
        validate_in_process(
            "chat2api",
            _candidate(config),
            config_path=config.resolved_path,
            app_dir=meta.relative_path,
        )
        matches = find_affected_dependents(self.apps, previous, config)
        if not matches:
            return ()
        dialog = BlastRadiusDialog(matches, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selected_ids = set(dialog.selected_app_ids())
        return tuple(match for match in matches if match.meta.id in selected_ids)

    def _on_restart_requested(self, app_id: str) -> None:
        # A restart writes no configuration and clears no dirty state.
        self.supervisor_manager.restart_service(app_id)

    def _request_saved_restart(self, app_id: str) -> None:
        self._save_restart_pending.add(app_id)
        self.supervisor_manager.restart_service(app_id)
        if app_id in self._save_restart_pending:
            self._save_restart_pending.discard(app_id)
            self.views[app_id].show_config_error("Configuration saved. Restart requested.")

    def _on_fetch_models(self, request: ModelFetchRequest) -> None:
        meta = self.apps.get(request.app_id)
        if meta is None:
            raise ConfigError("Model fetch origin is not a managed app.")
        if meta.config_kind not in ("llm", "chat2api", "file-bridge"):
            raise UnknownConfigKindError(meta.config_kind)
        if meta.config_kind != "llm":
            raise ConfigError("Model fetching is available only for LLM configurations.")
        worker = ModelFetchWorker(request)
        key = id(worker)
        self._model_workers[key] = worker
        worker.signals.finished.connect(
            partial(self._finish_model_worker, request.app_id, key),
            Qt.ConnectionType.QueuedConnection,
        )
        self.thread_pool.start(worker)

    def _finish_model_worker(
        self, app_id: str, key: int, response: ModelFetchResponse
    ) -> None:
        self._model_workers.pop(key, None)
        self._on_models_fetched(app_id, response)

    def _on_models_fetched(self, app_id: str, response: ModelFetchResponse) -> None:
        """Route a response to the app that asked, never the selected one."""
        meta, view = self.apps.get(app_id), self.views.get(app_id)
        if meta is None or view is None:
            return
        if meta.config_kind == "llm":
            view.on_model_fetch_response(response)
        elif meta.config_kind in ("chat2api", "file-bridge"):
            return
        else:
            raise UnknownConfigKindError(meta.config_kind)

    def _start_launcher_probes(self) -> None:
        """Probe each distinct chat2api app directory at most once per session."""
        for app_id, meta in self.apps.items():
            if meta.config_kind == "llm" or meta.config_kind == "file-bridge":
                continue
            if meta.config_kind != "chat2api":
                raise UnknownConfigKindError(meta.config_kind)
            key = meta.relative_path.resolve()
            if key in self._launcher_gate_cache:
                self.views[app_id].set_launcher_gate(self._launcher_gate_cache[key])
                continue
            self._launcher_gate_cache[key] = None
            job = LauncherProbeJob(meta)
            self._probe_jobs[key] = job
            self.views[app_id].set_launcher_gate(None)
            job.signals.probe_finished.connect(
                self._on_launcher_probe_finished, Qt.ConnectionType.QueuedConnection
            )
            self.thread_pool.start(job)

    @pyqtSlot(str, object)
    def _on_launcher_probe_finished(
        self, app_id: str, result: LauncherProbeResult
    ) -> None:
        if app_id not in self.apps or self.apps[app_id].config_kind != "chat2api":
            return
        key = self.apps[app_id].relative_path.resolve()
        self._launcher_gate_cache[key] = result
        self._probe_jobs.pop(key, None)
        for other_id, meta in self.apps.items():
            if meta.config_kind == "chat2api" and meta.relative_path.resolve() == key:
                self.views[other_id].set_launcher_gate(result)

    def _update_auth_warnings(self) -> None:
        for app_id, meta in self.apps.items():
            if meta.config_kind not in ("llm", "chat2api", "file-bridge"):
                raise UnknownConfigKindError(meta.config_kind)
            if meta.config_kind != "chat2api":
                continue
            warnings = []
            current = self._draft_configs.get(app_id)
            if isinstance(current, StructuredDoc) and (
                current.existed or current.create_requested
            ):
                try:
                    tree = _candidate(current)
                    auth = tree.get("server", {}).get(
                        "auth_token_env", "CHAT2API_TOKEN"
                    )
                    _, _, url = endpoint(current)
                    for other_id, other_meta in self.apps.items():
                        config = self._draft_configs.get(other_id)
                        if (
                            other_meta.config_kind == "llm"
                            and isinstance(config, AppAIConfig)
                            and urls_match(config.api_base, url)
                        ):
                            warning = auth_mismatch_warning(config, auth)
                            if warning:
                                warnings.append(warning.format(app_id=other_id))
                except (ConfigError, ValueError):
                    pass
            self.views[app_id].show_auth_warnings(tuple(warnings))

    def _reconcile_dependent_views(self, saved_dependents: dict[str, AppAIConfig]) -> None:
        """Install committed dependent baselines without discarding dirty drafts."""
        for app_id, baseline in saved_dependents.items():
            dirty = self._is_dirty(app_id)
            self._saved_configs[app_id] = baseline.model_copy(deep=True)
            if not dirty:
                self._draft_configs[app_id] = baseline.model_copy(deep=True)
            self.views[app_id].adopt_saved_baseline(baseline, preserve_draft=dirty)
            self._set_dirty_indicator(app_id)

    @pyqtSlot(str, object)
    def _on_structured_saved(self, app_id: str, result: SaveResult) -> None:
        should_restart = self._pending_restarts.pop(app_id, False)
        self._save_jobs.pop(app_id, None)
        self._saved_configs[app_id] = copy.deepcopy(result.document)
        self._draft_configs[app_id] = copy.deepcopy(result.document)
        view = self.views[app_id]
        view.adopt_saved_baseline(result.document, preserve_draft=False)
        view.set_validation_result(result.validation)
        view.set_save_in_progress(False)
        self._update_configured_port(app_id, result.document)
        self._set_dirty_indicator(app_id)
        self._reconcile_dependent_views(result.saved_dependents)
        self._update_auth_warnings()
        if should_restart:
            self._request_saved_restart(app_id)
        else:
            view.show_config_error("Configuration saved.")

    @pyqtSlot(str, object)
    def _on_structured_save_failed(self, app_id: str, error: ConfigError) -> None:
        self._pending_restarts.pop(app_id, None)
        self._save_jobs.pop(app_id, None)
        view = self.views[app_id]
        view.set_save_in_progress(False)
        self._set_dirty_indicator(app_id)
        if isinstance(error, ConfigValidationError) and isinstance(
            view, StructuredConfigView
        ):
            view.show_config_error(str(error))
            view.show_field_issues(error.issues)
        elif isinstance(error, (ServiceValidationError, ServiceValidationTimeout)):
            view.show_config_error(str(error), error.stderr)
        elif isinstance(error, StaleDocumentError):
            view.show_config_error(str(error))
            dialog = StaleDocumentDialog(error.path, self)
            dialog.exec()
            if dialog.choice() == "reload":
                self._reload_config(app_id)
            elif dialog.choice() == "diff":
                try:
                    current = error.path.read_bytes()
                    draft = self._draft_configs[app_id]
                    if not isinstance(draft, StructuredDoc):
                        raise ConfigError("The current draft is not a structured document.")
                    ReviewChangesDialog(
                        current, render(draft.kind, draft), error.path, self
                    ).exec()
                except (OSError, ConfigError) as exc:
                    view.show_config_error(str(error), str(exc))
        elif isinstance(error, TransactionError):
            view.show_config_error(str(error))
            TransactionReportDialog(error.report, self).exec()
        else:
            view.show_config_error(str(error))

    def _request_saved_restart(self, app_id: str) -> None:
        self.views[app_id].show_config_error("Configuration saved. Restart requested.")
        self._save_restart_pending.add(app_id)
        self._submitting_restart = app_id
        try:
            self.supervisor_manager.restart_service(app_id)
        finally:
            self._submitting_restart = None

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
        for app_id in self.apps:
            reported = status.services.get(app_id)
            if status.is_running and reported is not None:
                normalized_status = reported
            else:
                normalized_status = ServiceStatus(
                    service_id=app_id, state=ServiceRunState.UNKNOWN
                )
            self.sidebar.update_status(app_id, normalized_status)
            if app_id in self.views:
                self.views[app_id].update_service_status(normalized_status)

    def _on_supervisor_btn_clicked(self) -> None:
        if self._supervisor_action_btn.text() == "Start Supervisor":
            self.supervisor_manager.start_supervisor()
        else:
            self.supervisor_manager.start_supervisor()

    def _on_supervisor_action(self, action: str, success: bool, msg: str) -> None:
        if action.startswith("restart "):
            app_id = action[len("restart ") :]
        elif action == "restart":
            app_id = self._submitting_restart
        else:
            app_id = None
        if app_id is not None and app_id in self._save_restart_pending:
            self._save_restart_pending.remove(app_id)
            self.views[app_id].show_config_error(
                "service restart succeeded"
                if success
                else f"Configuration saved, but service restart failed: {msg}"
            )
        elif not success:
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
        return any(self._is_dirty(app_id) for app_id in self.apps)

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
