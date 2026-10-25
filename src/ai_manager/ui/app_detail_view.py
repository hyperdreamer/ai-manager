from pathlib import Path
from typing import List, Optional
from PyQt6.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from ai_manager.config.models import (
    AppAIConfig,
    AppMetadata,
    ConfigSnapshot,
    ModelFetchRequest,
    ModelFetchResponse,
    ProviderPreset,
    ServiceRunState,
    ServiceStatus,
)
from ai_manager.config.presets import DEFAULT_PRESETS, resolve_preset
from ai_manager.config.protocols import (
    PROTOCOLS,
    base_conflicts_with_endpoint,
    compose_request_url,
    effective_api_base,
)
from ai_manager.services.protocol_capability import ProtocolSupport, ProtocolSupportStatus
from ai_manager.services.supervisor import default_log_path
from ai_manager.ui.mnemonic import escape_mnemonic
from ai_manager.ui.widgets.api_key_input import ApiKeyInputWidget
from ai_manager.ui.widgets.log_view import LogViewWidget
from ai_manager.ui.widgets.model_combo import ModelComboBox
from ai_manager.ui.widgets.status_badge import StatusBadge


class AppDetailView(QWidget):
    """Detailed view for configuring a target application."""

    # Payloads are ``object`` so one Qt connection signature serves both the LLM
    # and structured adapters stored in ``MainWindow.views``.
    save_requested = pyqtSignal(str, object, bool)  # app_id, config, should_restart
    restart_requested = pyqtSignal(str)
    fetch_models_requested = pyqtSignal(ModelFetchRequest)
    config_changed = pyqtSignal(str, object)
    reload_requested = pyqtSignal(str)

    def __init__(self, app_meta: AppMetadata, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("appDetailView")
        self.app_meta = app_meta
        self._current_config: AppAIConfig | None = None
        self._snapshot: ConfigSnapshot | None = None
        self._loaded_endpoint = self._loaded_endpoint_raw = None
        self._endpoint = self._endpoint_raw = None
        self._protocol_edited = False
        self._protocol_combo: QComboBox | None = None
        self._protocol_hint = self._request_url_label = self._capability_notice = None
        self._protocol_labels = ("Auto — omit the key",) + tuple(
            f"{p.label} — {p.value}" for p in PROTOCOLS
        )
        self._protocol_support = ProtocolSupport(ProtocolSupportStatus.UNVERIFIABLE)
        self._load_failed = False
        self._conflicts: tuple[str, ...] = ()
        self._recovery_message = self._recovery_detail = ""
        self._ordinary_message = self._ordinary_detail = ""
        self._saving = False
        self._available_models: List[str] = []
        self._fetch_token = 0
        self._is_loading = False
        self._known_log_path: Optional[str] = None

        self._init_ui()
        self._refresh_protocol_presentation()
        self._refresh_save_enablement()

    @property
    def log_view(self) -> LogViewWidget:
        return self._log_view_widget

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header Bar
        header_frame = QFrame(self)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title_box = QVBoxLayout()
        self._title_label = QLabel(f"{self.app_meta.display_name} (Port {self.app_meta.default_port})", self)
        self._title_label.setObjectName("appTitleLabel")
        self._desc_label = QLabel(self.app_meta.description, self)
        self._desc_label.setObjectName("appDescLabel")
        title_box.addWidget(self._title_label)
        title_box.addWidget(self._desc_label)

        self._status_badge = StatusBadge(self)

        self._restart_btn = QPushButton("Restart Service Only", self)
        self._restart_btn.clicked.connect(lambda: self.restart_requested.emit(self.app_meta.id))

        header_layout.addLayout(title_box, stretch=1)
        header_layout.addWidget(self._status_badge)
        header_layout.addWidget(self._restart_btn)
        main_layout.addWidget(header_frame)

        # Plain-text save/validation outcome, mirroring the structured adapter.
        self._config_error_label = QLabel(self)
        self._config_error_label.setTextFormat(Qt.TextFormat.PlainText)
        self._config_error_label.setWordWrap(True)
        self._config_error_details = QPlainTextEdit(self)
        self._config_error_details.setReadOnly(True)
        self._config_error_details.hide()
        main_layout.addWidget(self._config_error_label)
        main_layout.addWidget(self._config_error_details)
        self._reload_btn = QPushButton("Reload configuration", self)
        self._reload_btn.clicked.connect(lambda: self.reload_requested.emit(self.app_meta.id))
        self._reload_btn.hide()
        main_layout.addWidget(self._reload_btn)

        # Scroll Area for forms
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content_widget = QWidget(scroll)
        form_layout = QVBoxLayout(content_widget)
        form_layout.setSpacing(14)

        # Group 1: Provider Settings
        provider_group = QGroupBox("AI Provider Settings", content_widget)
        self._provider_group = provider_group
        p_layout = QVBoxLayout(provider_group)
        p_layout.setSpacing(8)

        # Preset row
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:", self))
        self._preset_combo = QComboBox(self)
        preset_row.addWidget(self._preset_combo, stretch=1)

        self._fetch_btn = QPushButton("🔄 Fetch Available Models", self)
        self._fetch_btn.setObjectName("fetchBtn")
        self._fetch_btn.clicked.connect(self._on_fetch_clicked)
        preset_row.addWidget(self._fetch_btn)
        p_layout.addLayout(preset_row)

        if self.app_meta.supports_protocol_selection:
            p_layout.addWidget(QLabel("Upstream protocol", self))
            self._protocol_combo = QComboBox(self)
            self._protocol_combo.addItem(self._protocol_labels[0], None)
            for label, protocol in zip(self._protocol_labels[1:], PROTOCOLS):
                self._protocol_combo.addItem(label, protocol.value)
            self._protocol_combo.currentIndexChanged.connect(self._on_protocol_selected)
            self._protocol_combo.activated.connect(self._on_protocol_selected)
            p_layout.addWidget(self._protocol_combo)
            self._protocol_hint = QLabel(self)
            self._protocol_hint.setWordWrap(True)
            p_layout.addWidget(self._protocol_hint)
            self._capability_notice = QLabel(self)
            self._capability_notice.setWordWrap(True)
            self._capability_notice.setStyleSheet("color: #f59e0b;")
            p_layout.addWidget(self._capability_notice)

        for preset_id in (preset.id for preset in DEFAULT_PRESETS):
            preset = resolve_preset(preset_id)
            if preset is None or (preset.endpoint is not None and (
                not self.app_meta.supports_protocol_selection or self._protocol_combo is None
            )):
                continue
            self._preset_combo.addItem(preset.name, preset.id)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        self._preset_combo.activated.connect(self._on_preset_selected)

        # Base URL
        p_layout.addWidget(QLabel("API Base URL:", self))
        self._base_url_edit = QLineEdit(self)
        self._base_url_edit.textChanged.connect(self._on_field_changed)
        p_layout.addWidget(self._base_url_edit)
        if self.app_meta.supports_protocol_selection:
            self._request_url_label = QLabel(self)
            self._request_url_label.setWordWrap(True)
            p_layout.addWidget(self._request_url_label)

        # API Key
        p_layout.addWidget(QLabel("API Key (or $ENV_VAR):", self))
        self._key_edit = ApiKeyInputWidget(self)
        self._key_edit.textChanged.connect(self._on_field_changed)
        p_layout.addWidget(self._key_edit)

        # Fetch status message
        self._fetch_status_label = QLabel(self)
        self._fetch_status_label.setStyleSheet("font-size: 11px;")
        p_layout.addWidget(self._fetch_status_label)

        form_layout.addWidget(provider_group)

        # Group 2: Model Settings
        model_group = QGroupBox("Model Configuration", content_widget)
        self._model_group = model_group
        m_layout = QVBoxLayout(model_group)
        m_layout.setSpacing(8)

        # Split model checkbox (if supported)
        self._split_chk = QCheckBox("Split OCR and Text Models", self)
        if self.app_meta.supports_split_models:
            self._split_chk.toggled.connect(self._on_split_toggled)
            m_layout.addWidget(self._split_chk)
        else:
            self._split_chk.setVisible(False)

        # Unified model box
        self._unified_box = QWidget(self)
        u_layout = QVBoxLayout(self._unified_box)
        u_layout.setContentsMargins(0, 0, 0, 0)
        u_layout.addWidget(QLabel("Model:", self))
        self._model_combo = ModelComboBox(self)
        self._model_combo.currentTextChanged.connect(self._on_field_changed)
        u_layout.addWidget(self._model_combo)

        # Split models box
        self._split_box = QWidget(self)
        s_layout = QVBoxLayout(self._split_box)
        s_layout.setContentsMargins(0, 0, 0, 0)
        s_layout.addWidget(QLabel("OCR Model:", self))
        self._ocr_combo = ModelComboBox(self)
        self._ocr_combo.currentTextChanged.connect(self._on_field_changed)
        s_layout.addWidget(self._ocr_combo)

        s_layout.addWidget(QLabel("Text Model:", self))
        self._text_combo = ModelComboBox(self)
        self._text_combo.currentTextChanged.connect(self._on_field_changed)
        s_layout.addWidget(self._text_combo)
        self._split_box.setVisible(False)

        m_layout.addWidget(self._unified_box)
        m_layout.addWidget(self._split_box)

        # Quick picks tag chips
        chips_header = QLabel("Quick picks from provider:", self)
        chips_header.setObjectName("formSectionMuted")
        m_layout.addWidget(chips_header)

        self._chips_layout = QHBoxLayout()
        self._chips_layout.setSpacing(6)
        m_layout.addLayout(self._chips_layout)

        form_layout.addWidget(model_group)
        form_layout.addStretch(1)

        scroll.setWidget(content_widget)

        # Footer Action Bar
        footer = QFrame(self)
        footer.setObjectName("footerActionBar")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 8, 0, 0)

        self._dirty_label = QLabel(self)
        self._dirty_label.setStyleSheet("color: #f59e0b; font-weight: 500;")

        self._save_only_btn = QPushButton("Save Config Only", self)
        self._save_only_btn.clicked.connect(lambda: self._emit_save(restart=False))

        self._save_restart_btn = QPushButton("Save and Restart Service", self)
        self._save_restart_btn.setObjectName("primaryActionBtn")
        self._save_restart_btn.clicked.connect(lambda: self._emit_save(restart=True))

        footer_layout.addWidget(self._dirty_label)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self._save_only_btn)
        footer_layout.addWidget(self._save_restart_btn)

        # Configuration page owns the form scroll area and the action footer.
        config_page = QWidget(self)
        config_layout = QVBoxLayout(config_page)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(0)
        config_layout.addWidget(scroll, stretch=1)
        config_layout.addWidget(footer)

        # Logs page is the live log view itself; QTabWidget reparents it.
        self._log_view_widget = LogViewWidget(self.app_meta.id, self)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(config_page, "Configuration")
        self._tabs.addTab(self._log_view_widget, "Logs")
        self._tabs.setCurrentIndex(0)
        main_layout.addWidget(self._tabs, stretch=1)
        for label in self.findChildren(QLabel):
            label.setTextFormat(Qt.TextFormat.PlainText)

    def load_config(self, snapshot: ConfigSnapshot) -> None:
        owned = ConfigSnapshot(snapshot.config, snapshot.sha256, snapshot.api_base_present)
        baseline = owned.config.model_copy(deep=True)
        old = (
            self._snapshot, self._current_config, self._loaded_endpoint,
            self._loaded_endpoint_raw, self._endpoint, self._endpoint_raw, self._protocol_edited,
        )
        try:
            self._snapshot, self._current_config = owned, baseline
            self._loaded_endpoint = baseline.endpoint if self.app_meta.supports_protocol_selection else None
            self._loaded_endpoint_raw = baseline.endpoint_raw if self.app_meta.supports_protocol_selection else None
            self._display_draft(baseline)
        except Exception:
            (
                self._snapshot, self._current_config, self._loaded_endpoint,
                self._loaded_endpoint_raw, self._endpoint, self._endpoint_raw, self._protocol_edited,
            ) = old
            self._refresh_save_enablement()
            raise
        self._refresh_save_enablement()

    def _display_draft(self, draft: AppAIConfig) -> None:
        """Populate controls silently without publishing a saved baseline."""
        was_loading = self._is_loading
        self._is_loading = True
        blockers = []
        try:
            controls = (
                self._base_url_edit, self._key_edit, self._preset_combo, self._split_chk,
                self._model_combo, self._ocr_combo, self._text_combo,
            )
            if self._protocol_combo is not None:
                controls += (self._protocol_combo,)
            blockers = [QSignalBlocker(control) for control in controls]
            self._base_url_edit.setText(draft.api_base)
            self._key_edit.setText(draft.api_key)
            matched = False
            for idx in range(self._preset_combo.count()):
                preset_id = self._preset_combo.itemData(idx)
                preset = resolve_preset(preset_id)
                if (preset is not None
                        and preset.api_base.rstrip("/") == draft.api_base.rstrip("/")
                        and (preset.endpoint is None or (
                            preset.endpoint == draft.endpoint and draft.endpoint_raw is None
                        ))):
                    self._preset_combo.setCurrentIndex(idx)
                    matched = True
                    break
            if not matched:
                custom_idx = self._preset_combo.findData("custom")
                if custom_idx >= 0:
                    self._preset_combo.setCurrentIndex(custom_idx)

            split = draft.is_split_model and self.app_meta.supports_split_models
            self._split_chk.setChecked(split)
            self._split_box.setVisible(split)
            self._unified_box.setVisible(not split)
            for combo, current in (
                (self._model_combo, None if split else draft.model),
                (self._ocr_combo, draft.ocr_model if split else None),
                (self._text_combo, draft.text_model if split else None),
            ):
                # ModelComboBox retains old text for a None current value and
                # selects its first new item. Explicitly keep blank forms blank.
                combo.setCurrentIndex(-1)
                combo.setEditText("")
                combo.set_models(self._available_models, current=current)
                if current is None:
                    combo.setCurrentIndex(-1)
                    combo.setEditText("")

            self._endpoint = draft.endpoint if self.app_meta.supports_protocol_selection else None
            self._endpoint_raw = draft.endpoint_raw if self.app_meta.supports_protocol_selection else None
            self._protocol_edited = (self._endpoint, self._endpoint_raw) != (
                self._loaded_endpoint, self._loaded_endpoint_raw
            )
            if self._protocol_combo is not None:
                if self._protocol_combo.count() > 4:
                    self._protocol_combo.removeItem(4)
                if self._endpoint_raw is not None:
                    self._protocol_combo.addItem(f"Invalid: {self._endpoint_raw}")
                    self._protocol_combo.model().item(4).setEnabled(False)
                    self._protocol_combo.setCurrentIndex(4)
                else:
                    self._protocol_combo.setCurrentIndex(self._protocol_combo.findData(self._endpoint))
            self._refresh_protocol_presentation()
        finally:
            for blocker in blockers:
                blocker.unblock()
            self._is_loading = was_loading

    def get_current_draft(self) -> AppAIConfig:
        is_split = self._split_chk.isChecked() if self.app_meta.supports_split_models else False
        return AppAIConfig(
            api_base=self._base_url_edit.text().strip(),
            api_key=self._key_edit.text().strip(),
            is_split_model=is_split,
            model=self._model_combo.currentText().strip() if not is_split else None,
            ocr_model=self._ocr_combo.currentText().strip() if is_split else None,
            text_model=self._text_combo.currentText().strip() if is_split else None,
            endpoint=self._endpoint if self.app_meta.supports_protocol_selection else None,
            endpoint_raw=self._endpoint_raw if self.app_meta.supports_protocol_selection else None,
        )

    def adopt_saved_baseline(self, snapshot: ConfigSnapshot, *, preserve_draft: bool) -> tuple[str, ...]:
        """Install a saved baseline, rebasing each visible logical field."""
        if not preserve_draft or self._snapshot is None:
            self.load_config(snapshot)
            return ()

        order = (
            "api_base", "api_key", "endpoint", "is_split_model",
            "model", "ocr_model", "text_model",
        )

        def values(config: AppAIConfig) -> dict:
            result = config.model_dump()
            result["endpoint"] = (config.endpoint, config.endpoint_raw)
            result.pop("endpoint_raw")
            return result

        old_snapshot = self._snapshot
        old_draft = self.get_current_draft()
        old = (
            self._snapshot, self._current_config, self._loaded_endpoint,
            self._loaded_endpoint_raw, self._endpoint, self._endpoint_raw,
            self._protocol_edited, self._is_loading,
        )
        loaded, draft, committed = (
            values(old_snapshot.config),
            values(old_draft),
            values(snapshot.config),
        )
        merged, conflicts = {}, set()
        for name in order:
            if draft[name] == loaded[name]:
                merged[name] = committed[name]
            elif committed[name] == loaded[name] or draft[name] == committed[name]:
                merged[name] = draft[name]
            else:
                merged[name] = draft[name]
                conflicts.add(name)

        cross = []
        for leaf in ("model", "ocr_model", "text_model"):
            if (
                committed["is_split_model"] != loaded["is_split_model"]
                and draft[leaf] != loaded[leaf]
                and draft[leaf] != committed[leaf]
            ) or (
                draft["is_split_model"] != loaded["is_split_model"]
                and committed[leaf] != loaded[leaf]
                and committed[leaf] != draft[leaf]
            ):
                cross.append(leaf)
        if cross:
            conflicts.update(("is_split_model", *cross))
            merged["is_split_model"] = draft["is_split_model"]
            for leaf in ("model", "ocr_model", "text_model"):
                merged[leaf] = draft[leaf]

        endpoint, endpoint_raw = merged.pop("endpoint")
        merged.update(endpoint=endpoint, endpoint_raw=endpoint_raw)
        merged_config = AppAIConfig.model_validate(merged)

        try:
            self.load_config(snapshot)
            self._display_draft(merged_config)
        except Exception:
            try:
                self.load_config(old_snapshot)
                self._display_draft(old_draft)
            except Exception:
                pass
            (
                self._snapshot, self._current_config, self._loaded_endpoint,
                self._loaded_endpoint_raw, self._endpoint, self._endpoint_raw,
                self._protocol_edited, self._is_loading,
            ) = old
            self._refresh_save_enablement()
            raise

        return tuple(name for name in order if name in conflicts)

    def _on_protocol_selected(self, index: int) -> None:
        if self._is_loading or self._protocol_combo is None or index not in range(4):
            return
        before = (self._endpoint, self._endpoint_raw)
        self._endpoint = self._protocol_combo.itemData(index)
        self._endpoint_raw = None
        self._protocol_edited = (self._endpoint, self._endpoint_raw) != (
            self._loaded_endpoint, self._loaded_endpoint_raw
        )
        self._refresh_protocol_presentation()
        if before != (self._endpoint, self._endpoint_raw):
            self._on_field_changed()

    def set_protocol_support(self, support: ProtocolSupport) -> None:
        self._protocol_support = support
        self._refresh_protocol_presentation()
        self._refresh_config_outcome()

    def _refresh_protocol_presentation(self) -> None:
        if self._protocol_combo is None:
            return
        support = self._protocol_support
        all_available = support.status in (
            ProtocolSupportStatus.SUPPORTED, ProtocolSupportStatus.UNVERIFIABLE
        )
        with QSignalBlocker(self._protocol_combo):
            for index, label in enumerate(self._protocol_labels):
                value = self._protocol_combo.itemData(index)
                enabled = (value is None or all_available or value in support.accepted
                           or value == self._loaded_endpoint)
                self._protocol_combo.model().item(index).setEnabled(enabled)
                self._protocol_combo.setItemText(index, label + ("" if enabled else " unavailable"))
            if self._endpoint_raw is None and self._protocol_combo.count() > 4:
                self._protocol_combo.removeItem(4)

        if support.status is ProtocolSupportStatus.SUPPORTED:
            notice = ""
        elif support.status is ProtocolSupportStatus.UNVERIFIABLE:
            notice = "Protocol support could not be verified — validated by ai-manager only."
        else:
            notice = (
                "Installed build failed protocol compatibility checks. Update the service to enable "
                "protocol selection. Auto stays selectable so a saved protocol can be removed."
            )
        self._capability_notice.setText(notice)
        self._capability_notice.setVisible(bool(notice))
        invalid = self._endpoint_raw is not None
        self._protocol_combo.setStyleSheet("color: #ef4444;" if invalid else "")
        self._base_url_edit.setStyleSheet("")
        self._protocol_hint.setStyleSheet("color: #ef4444;" if invalid else "")
        if invalid:
            repair = "Not one of the three supported protocols. Pick a valid one, or Auto to remove the key."
            self._protocol_hint.setText("Unavailable — " + repair)
            self._request_url_label.setText("Request URL: unavailable — " + repair)
            self._request_url_label.setStyleSheet("color: #ef4444;")
            return
        hint = "legacy Chat Completions - Authorization: Bearer"
        if self._endpoint is not None:
            hint = "Sends " + next(p.auth_hint for p in PROTOCOLS if p.value == self._endpoint)
        self._protocol_hint.setText(hint)
        if self._snapshot is None:
            self._request_url_label.setText("")
            return
        draft = self.get_current_draft()
        base = effective_api_base(self.app_meta.id, draft, self._snapshot)
        conflict = base_conflicts_with_endpoint(base, self._endpoint)
        self._base_url_edit.setStyleSheet("border: 1px solid #ef4444;" if conflict else "")
        self._request_url_label.setStyleSheet("color: #ef4444;" if conflict else "color: #67e8f9;")
        self._request_url_label.setText(
            f"Request URL: {compose_request_url(self.app_meta.id, base, self._endpoint)}"
        )

    def show_config_error(self, message: str, detail: str = "") -> None:
        """Keep ordinary outcomes separate from recovery and probe diagnostics."""
        self._ordinary_message, self._ordinary_detail = message, detail
        self._refresh_config_outcome()

    def _refresh_config_outcome(self) -> None:
        recovery = self._load_failed or bool(self._conflicts)
        if recovery:
            message, detail = self._recovery_message, self._recovery_detail
        else:
            message, detail = self._ordinary_message, self._ordinary_detail
            notice = not message or message.startswith("Configuration saved") or message == "service restart succeeded"
            if notice and not detail and self._protocol_support.status is not ProtocolSupportStatus.SUPPORTED:
                detail = self._protocol_support.detail
        self._config_error_label.setText(message)
        self._config_error_details.setPlainText(detail)
        self._config_error_details.setVisible(bool(detail))
        self._reload_btn.setVisible(recovery)

    def set_recovery_state(
        self, *, load_failed: bool, conflicts: tuple[str, ...] = (), message: str = "", detail: str = ""
    ) -> None:
        self._load_failed, self._conflicts = load_failed, conflicts
        self._recovery_message = message or (
            "Configuration changed while you were editing. Reload the configuration before saving."
            if conflicts else "Reload the configuration before saving."
        )
        self._recovery_detail = detail or (
            f"Conflicting fields: {', '.join(conflicts)}." if conflicts else ""
        )
        self._refresh_config_outcome()
        self._refresh_save_enablement()

    def _refresh_save_enablement(self) -> None:
        editable = self._snapshot is not None and not self._saving
        saveable = editable and not self._load_failed and not self._conflicts
        self._provider_group.setEnabled(editable)
        self._model_group.setEnabled(editable)
        self._save_only_btn.setEnabled(bool(saveable))
        self._save_restart_btn.setEnabled(bool(saveable))

    def set_save_in_progress(self, saving: bool) -> None:
        """Disable configuration editing only; logs and restart stay available."""
        self._saving = saving
        self._refresh_save_enablement()

    def update_service_status(self, status: ServiceStatus) -> None:
        if status.log_path:
            self._known_log_path = str(status.log_path)
        if self._known_log_path is not None:
            path = self._known_log_path
        else:
            fallback: Path = default_log_path(self.app_meta.id)
            path = str(fallback)
        self._log_view_widget.set_log_path(path)
        self._log_view_widget.set_service_state(status.state)
        self._status_badge.set_status(status.state, status.pid)

    def set_available_models(self, models: List[str]) -> None:
        self._available_models = models
        cur_draft = self.get_current_draft()

        self._display_draft(cur_draft)

        # Populate quick pick chips
        self._render_chips(models[:6])

    def _render_chips(self, models: List[str]) -> None:
        # Clear existing chips
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for m_name in models:
            chip = QToolButton(self)
            chip.setObjectName("modelChip")
            # Model names come from arbitrary provider responses; QToolButton
            # would swallow a single '&' as a mnemonic marker.
            chip.setText(escape_mnemonic(m_name))
            chip.clicked.connect(lambda _, name=m_name: self._apply_model_choice(name))
            self._chips_layout.addWidget(chip)

        self._chips_layout.addStretch(1)

    def _apply_model_choice(self, model_name: str) -> None:
        if self._split_chk.isChecked():
            self._text_combo.setEditText(model_name)
        else:
            self._model_combo.setEditText(model_name)

    def on_model_fetch_response(self, response: ModelFetchResponse) -> None:
        if response.token != self._fetch_token:
            return  # Stale response

        if response.success:
            self._fetch_status_label.setText(
                f"✓ Fetched {len(response.models)} models from {response.endpoint_used}"
            )
            self._fetch_status_label.setStyleSheet("font-size: 11px; color: #10b981;")
            self.set_available_models(response.models)
        else:
            self._fetch_status_label.setText(f"⚠️ {response.error_message}")
            self._fetch_status_label.setStyleSheet("font-size: 11px; color: #ef4444;")

    def _on_fetch_clicked(self) -> None:
        self._fetch_token += 1
        draft = self.get_current_draft()
        req = ModelFetchRequest(
            token=self._fetch_token,
            api_base=draft.api_base,
            api_key=draft.api_key,
            endpoint=draft.endpoint,
            app_id=self.app_meta.id,
        )
        self._fetch_status_label.setText("Fetching models from provider...")
        self._fetch_status_label.setStyleSheet("font-size: 11px; color: #3b82f6;")
        self.fetch_models_requested.emit(req)

    def _on_preset_selected(self) -> None:
        if self._is_loading:
            return
        preset = resolve_preset(self._preset_combo.currentData())
        if preset is not None:
            self._apply_preset(preset)

    def _apply_preset(self, preset: ProviderPreset) -> None:
        if preset.id == "custom":
            return
        before = self.get_current_draft()
        values = before.model_dump()
        values["api_base"] = preset.api_base
        if preset.default_key_env_var:
            values["api_key"] = f"${preset.default_key_env_var}"
        if preset.endpoint is not None:
            values["endpoint"], values["endpoint_raw"] = preset.endpoint, None
        after = AppAIConfig.model_validate(values)
        self._display_draft(after)
        if before != after:
            self.config_changed.emit(self.app_meta.id, after)

    def _on_split_toggled(self, checked: bool) -> None:
        self._split_box.setVisible(checked)
        self._unified_box.setVisible(not checked)
        self._on_field_changed()

    def _on_field_changed(self) -> None:
        if self._is_loading:
            return
        self._protocol_edited = (self._endpoint, self._endpoint_raw) != (
            self._loaded_endpoint, self._loaded_endpoint_raw
        )
        self._refresh_protocol_presentation()
        draft = self.get_current_draft()
        self.config_changed.emit(self.app_meta.id, draft)

    def _emit_save(self, restart: bool) -> None:
        draft = self.get_current_draft()
        self.save_requested.emit(self.app_meta.id, draft, restart)
