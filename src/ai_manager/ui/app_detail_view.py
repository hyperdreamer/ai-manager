from typing import List, Optional
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from ai_manager.config.models import (
    AppAIConfig,
    AppMetadata,
    ModelFetchRequest,
    ModelFetchResponse,
    ProviderPreset,
    ServiceRunState,
    ServiceStatus,
)
from ai_manager.config.presets import DEFAULT_PRESETS
from ai_manager.ui.widgets.api_key_input import ApiKeyInputWidget
from ai_manager.ui.widgets.model_combo import ModelComboBox
from ai_manager.ui.widgets.status_badge import StatusBadge


class AppDetailView(QWidget):
    """Detailed view for configuring a target application."""

    save_requested = pyqtSignal(str, AppAIConfig, bool)  # app_id, config, should_restart
    restart_requested = pyqtSignal(str)
    fetch_models_requested = pyqtSignal(ModelFetchRequest)
    config_changed = pyqtSignal(str, AppAIConfig)

    def __init__(self, app_meta: AppMetadata, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_meta = app_meta
        self._current_config = AppAIConfig()
        self._available_models: List[str] = []
        self._fetch_token = 0
        self._is_loading = False

        self._init_ui()

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
        self._title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self._desc_label = QLabel(self.app_meta.description, self)
        self._desc_label.setStyleSheet("font-size: 11px; color: #888;")
        title_box.addWidget(self._title_label)
        title_box.addWidget(self._desc_label)

        self._status_badge = StatusBadge(self)

        self._restart_btn = QPushButton("Restart Service Only", self)
        self._restart_btn.clicked.connect(lambda: self.restart_requested.emit(self.app_meta.id))

        header_layout.addLayout(title_box, stretch=1)
        header_layout.addWidget(self._status_badge)
        header_layout.addWidget(self._restart_btn)
        main_layout.addWidget(header_frame)

        # Scroll Area for forms
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content_widget = QWidget(scroll)
        form_layout = QVBoxLayout(content_widget)
        form_layout.setSpacing(14)

        # Group 1: Provider Settings
        provider_group = QGroupBox("AI Provider Settings", content_widget)
        p_layout = QVBoxLayout(provider_group)
        p_layout.setSpacing(8)

        # Preset row
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:", self))
        self._preset_combo = QComboBox(self)
        for preset in DEFAULT_PRESETS:
            self._preset_combo.addItem(preset.name, preset.id)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        preset_row.addWidget(self._preset_combo, stretch=1)

        self._fetch_btn = QPushButton("🔄 Fetch Available Models", self)
        self._fetch_btn.setObjectName("fetchBtn")
        self._fetch_btn.clicked.connect(self._on_fetch_clicked)
        preset_row.addWidget(self._fetch_btn)
        p_layout.addLayout(preset_row)

        # Base URL
        p_layout.addWidget(QLabel("API Base URL:", self))
        self._base_url_edit = QLineEdit(self)
        self._base_url_edit.textChanged.connect(self._on_field_changed)
        p_layout.addWidget(self._base_url_edit)

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
        chips_header.setStyleSheet("font-size: 11px; color: #888;")
        m_layout.addWidget(chips_header)

        self._chips_layout = QHBoxLayout()
        self._chips_layout.setSpacing(6)
        m_layout.addLayout(self._chips_layout)

        form_layout.addWidget(model_group)
        form_layout.addStretch(1)

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll, stretch=1)

        # Footer Action Bar
        footer = QFrame(self)
        footer.setObjectName("footerActionBar")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 8, 0, 0)

        self._dirty_label = QLabel(self)
        self._dirty_label.setStyleSheet("color: #f59e0b; font-weight: 500;")

        self._save_only_btn = QPushButton("Save Config Only", self)
        self._save_only_btn.clicked.connect(lambda: self._emit_save(restart=False))

        self._save_restart_btn = QPushButton("Save & Restart App", self)
        self._save_restart_btn.setObjectName("primaryActionBtn")
        self._save_restart_btn.clicked.connect(lambda: self._emit_save(restart=True))

        footer_layout.addWidget(self._dirty_label)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self._save_only_btn)
        footer_layout.addWidget(self._save_restart_btn)

        main_layout.addWidget(footer)

    def load_config(self, config: AppAIConfig) -> None:
        self._is_loading = True
        self._current_config = config.model_copy()

        self._base_url_edit.setText(config.api_base)
        self._key_edit.setText(config.api_key)

        # Match preset if possible
        matched = False
        for idx in range(self._preset_combo.count()):
            preset_id = self._preset_combo.itemData(idx)
            for p in DEFAULT_PRESETS:
                if p.id == preset_id and p.api_base.rstrip("/") == config.api_base.rstrip("/"):
                    self._preset_combo.setCurrentIndex(idx)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            custom_idx = self._preset_combo.findData("custom")
            if custom_idx >= 0:
                self._preset_combo.setCurrentIndex(custom_idx)

        # Models
        if config.is_split_model and self.app_meta.supports_split_models:
            self._split_chk.setChecked(True)
            self._split_box.setVisible(True)
            self._unified_box.setVisible(False)
            self._ocr_combo.set_models(self._available_models, current=config.ocr_model)
            self._text_combo.set_models(self._available_models, current=config.text_model)
        else:
            self._split_chk.setChecked(False)
            self._split_box.setVisible(False)
            self._unified_box.setVisible(True)
            self._model_combo.set_models(self._available_models, current=config.model)

        self._is_loading = False

    def get_current_draft(self) -> AppAIConfig:
        is_split = self._split_chk.isChecked() if self.app_meta.supports_split_models else False
        return AppAIConfig(
            api_base=self._base_url_edit.text().strip(),
            api_key=self._key_edit.text().strip(),
            is_split_model=is_split,
            model=self._model_combo.currentText().strip() if not is_split else None,
            ocr_model=self._ocr_combo.currentText().strip() if is_split else None,
            text_model=self._text_combo.currentText().strip() if is_split else None,
        )

    def update_service_status(self, status: ServiceStatus) -> None:
        self._status_badge.set_status(status.state, status.pid)

    def set_available_models(self, models: List[str]) -> None:
        self._available_models = models
        cur_draft = self.get_current_draft()

        self._model_combo.set_models(models, current=cur_draft.model)
        self._ocr_combo.set_models(models, current=cur_draft.ocr_model)
        self._text_combo.set_models(models, current=cur_draft.text_model)

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
            chip.setText(m_name)
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
        req = ModelFetchRequest(
            token=self._fetch_token,
            api_base=self._base_url_edit.text().strip(),
            api_key=self._key_edit.text().strip(),
        )
        self._fetch_status_label.setText("Fetching models from provider...")
        self._fetch_status_label.setStyleSheet("font-size: 11px; color: #3b82f6;")
        self.fetch_models_requested.emit(req)

    def _on_preset_selected(self) -> None:
        if self._is_loading:
            return
        preset_id = self._preset_combo.currentData()
        for p in DEFAULT_PRESETS:
            if p.id == preset_id:
                if p.id != "custom":
                    self._base_url_edit.setText(p.api_base)
                    if p.default_key_env_var:
                        self._key_edit.setText(f"${p.default_key_env_var}")
                break

    def _on_split_toggled(self, checked: bool) -> None:
        self._split_box.setVisible(checked)
        self._unified_box.setVisible(not checked)
        self._on_field_changed()

    def _on_field_changed(self) -> None:
        if self._is_loading:
            return
        draft = self.get_current_draft()
        self.config_changed.emit(self.app_meta.id, draft)

    def _emit_save(self, restart: bool) -> None:
        draft = self.get_current_draft()
        self.save_requested.emit(self.app_meta.id, draft, restart)
