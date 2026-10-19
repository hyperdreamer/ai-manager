"""Declarative chat2api and file-bridge configuration widgets.

This module owns only widgets: every editable value, row and mutation lives in
:class:`StructuredEditorModel`, and every byte that reaches disk is rendered by
``structured_config.render``. The view builds the controls declared by the form
inventory (``SERVER_FIELDS``, ``FILE_BRIDGE_FIELDS``, ``PROVIDER_OPTIONS``),
forwards edits as addressed field writes, and renders the exact catalog text
for read-only reasons, validation results and gate state.

Two rules drive the control design:

* Explicit presence. A value is either absent (no mutation) or present with a
  value. ``PresenceControl`` keeps that distinction visible and never invents a
  default for an absent key.
* Never clamp. Integers are edited as text so an invalid loaded value
  (``"8964"``, ``8964.0``, ``true``) is preserved verbatim and reported by
  validation instead of being silently rewritten to a legal number.

Secrets are masked with a per-field ``Reveal`` checkbox. Revealing changes only
the echo mode; it never marks the field changed, so an untouched secret is
never written from widget text.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ai_manager.config.config_errors import (
    ConfigError,
    ConfigValidationError,
    MissingExampleError,
    UnknownConfigKindError,
)
from ai_manager.config.models import AppMetadata, ModelFetchRequest, ServiceStatus
from ai_manager.config.structured_config import effective_mutations, load_example, render
from ai_manager.config.structured_models import (
    FieldIssue,
    LauncherProbeResult,
    StructuredDoc,
    ValidationResult,
)
from ai_manager.config.structured_schema import (
    FILE_BRIDGE_FIELDS,
    PROVIDER_OPTIONS,
    SECRET_OPTION_KEYS,
    SERVER_FIELDS,
    OptionSpec,
)
from ai_manager.services.supervisor import default_log_path
from ai_manager.ui.config_dialogs import ReviewChangesDialog, _label
from ai_manager.ui.mnemonic import escape_mnemonic
from ai_manager.ui.structured_editor_model import StructuredEditorModel
from ai_manager.ui.widgets.log_view import LogViewWidget
from ai_manager.ui.widgets.status_badge import StatusBadge

# Exact user-visible strings from the specification's text catalog.
GATE_PENDING = "Checking whether launcher honors config\u2026"
GATE_PASSED = "launcher honors config \u2014 host/port editable"
GATE_FAILED = "launcher does not honor config \u2014 install Target B first"
GATE_BYPASS = (
    "Launcher has not passed the configuration probe; host/port changes "
    "cannot be saved."
)
NOT_VALIDATED = "Not validated since load."
SAVING = "Saving configuration\u2026"
INVALID_INPUT = "Configuration has invalid fields; nothing was saved."
UNINITIALIZED_SAVE = "Create a draft from the example before saving."
PROVIDER_WARNING = (
    "Provider changed. Existing options were kept and may not apply to the "
    "new provider."
)
MISSING_TARGET = (
    "Configuration file is missing. Choose Create from Example to start a draft."
)
READ_ONLY_MESSAGES = {
    "symlink": "Configuration path is a symlink; editing is disabled.",
    "non-writable": "Configuration is not writable; editing is disabled.",
    "yaml-anchors-aliases": (
        "YAML anchors or aliases are present; editing is disabled to preserve "
        "linked values."
    ),
    "non-dict-root": "Configuration root must be a mapping; save is disabled.",
    "missing-config": MISSING_TARGET,
    "load-error": "Cannot load configuration; save is disabled.",
}

LISTENER_ADDRESSES = (("server", "host"), ("server", "port"))

_EXPECTED_TYPE = {
    "text": str,
    "directory": str,
    "nullable-text": str,
    "secret": str,
    "integer": int,
    "boolean": bool,
}


def _reason_text(reasons: tuple[str, ...]) -> str:
    """Explain every read-only reason in visible plain text, in order."""
    lines = [
        READ_ONLY_MESSAGES.get(reason, "Configuration is read-only.")
        for reason in reasons
    ]
    return "\n".join(dict.fromkeys(lines))


class PresenceControl(QWidget):
    """One declared field with an explicit present/absent switch.

    ``written`` always carries the *effective* value: the typed text, the
    parsed JSON of an unusual loaded value, ``None`` for the nullable text
    control, or ``False`` (a delete) when the key is marked absent.
    """

    written = pyqtSignal(bool, object)

    def __init__(self, control, present, value, *, default=None, parent=None):
        super().__init__(parent)
        self.control = control
        self.changed = False
        self._loading = True
        stored = value if present else default
        self._value = copy.deepcopy(stored)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.present = QCheckBox("Present", self)
        self.present.setChecked(present)
        layout.addWidget(self.present)
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Absent")
        self.null: QCheckBox | None = None
        if control == "nullable-text":
            self.null = QCheckBox("Authentication disabled", self)
            self.null.setChecked(present and value is None)
            layout.addWidget(self.null)
            self.null.toggled.connect(self._write)
        expected = _EXPECTED_TYPE[control]
        self._raw_type = self._value is not None and (
            type(self._value) is not expected
            if expected in (int, bool)
            else not isinstance(self._value, expected)
        )
        self.edit.setText(self._display_text())
        if control == "secret":
            self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.edit, 1)
        self.reveal = QCheckBox("Reveal", self)
        self.reveal.setVisible(control == "secret")
        self.reveal.toggled.connect(self._set_echo)
        layout.addWidget(self.reveal)
        if control == "directory":
            pick = QPushButton("Choose Directory", self)
            pick.clicked.connect(self._pick)
            layout.addWidget(pick)
        self.present.toggled.connect(self._write)
        self.edit.textChanged.connect(self._write)
        self._loading = False
        self._enabled_value()

    # -- value rendering ------------------------------------------------------

    def _display_text(self) -> str:
        """Text that round-trips an unusual loaded value without clamping it.

        A value whose loaded type disagrees with the declared control is shown
        as its JSON form, so ``"8964"``, ``8964.0`` and ``true`` stay visibly
        distinct from the integer the schema wants instead of being coerced.
        """
        value = self._value
        if value is None:
            return ""
        if self._raw_type:
            try:
                return json.dumps(value, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError):
                # A mapping, sequence or YAML scalar that JSON cannot express
                # stays visible as text; validation reports it as invalid.
                return str(value)
        if type(value) is bool:
            return str(value).lower()
        return str(value)

    def _parse(self, text: str) -> Any:
        if self.null is not None and self.null.isChecked():
            return None
        if self._raw_type:
            try:
                return json.loads(text)
            except ValueError:
                return text
        if self.control == "integer":
            # Text that is not an integer stays text so validation reports it
            # instead of this widget substituting a legal number.
            return int(text) if re.fullmatch(r"[+-]?[0-9]+", text) else text
        if self.control == "boolean":
            return text.lower() == "true" if text.lower() in ("true", "false") else text
        return text

    # -- interaction ----------------------------------------------------------

    def _set_echo(self, visible: bool) -> None:
        """Reveal toggles masking only; it never records a value edit."""
        self.edit.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    def _pick(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Save root", self.edit.text())
        if directory:
            self.present.blockSignals(True)
            self.present.setChecked(True)
            self.present.blockSignals(False)
            # Only the draft text changes: picking never creates a directory.
            self.edit.setText(directory)

    def _enabled_value(self) -> None:
        off = self.null is not None and self.null.isChecked()
        self.edit.setEnabled(self.present.isChecked() and not off)
        if self.null is not None:
            self.null.setEnabled(self.present.isChecked())

    def _write(self, *args) -> None:
        self._enabled_value()
        if self._loading:
            return
        self.changed = True
        self.written.emit(self.present.isChecked(), self._parse(self.edit.text()))


class StructuredConfigView(QWidget):
    """Configuration/Logs page for one structured (non-LLM) application."""

    save_requested = pyqtSignal(str, object, bool)
    restart_requested = pyqtSignal(str)
    config_changed = pyqtSignal(str, object)
    # Declared for adapter symmetry. This view has no fetch controls and never
    # emits it; model discovery is an LLM-only feature.
    fetch_models_requested = pyqtSignal(ModelFetchRequest)

    def __init__(self, app_meta: AppMetadata, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if app_meta.config_kind not in ("chat2api", "file-bridge"):
            raise UnknownConfigKindError(app_meta.config_kind)
        self.app_meta = app_meta
        self._kind = app_meta.config_kind
        self._chat = app_meta.config_kind == "chat2api"
        self._model: StructuredEditorModel | None = None
        self._baseline: StructuredDoc | None = None
        self._fields: dict[tuple[str, ...], PresenceControl] = {}
        self._option_fields: dict[tuple[str, ...], PresenceControl] = {}
        self._row_issue_widgets: dict[tuple[str, ...], QWidget] = {}
        self._raw_toggles: dict[tuple[str, ...], QToolButton] = {}
        self._expanded_row_id: int | None = None
        self._expanded_identity: tuple[str | None, str] | None = None
        self._gate: LauncherProbeResult | None = None
        self._saving = False
        self._load_failed = False
        self._known_log_path: str | None = None
        self._build_chrome()

    # -- construction ---------------------------------------------------------

    def _build_chrome(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self._title_label = _label(
            f"{self.app_meta.display_name} (Port {self.app_meta.default_port})", self
        )
        self._status_badge = StatusBadge(self)
        self._restart_btn = QPushButton("Restart Service Only", self)
        self._restart_btn.clicked.connect(
            lambda: self.restart_requested.emit(self.app_meta.id)
        )
        header.addWidget(self._title_label, 1)
        header.addWidget(self._status_badge)
        header.addWidget(self._restart_btn)
        layout.addLayout(header)

        target = Path(self.app_meta.relative_path / self.app_meta.config_file_name).absolute()
        path_text = f"Editing {target}"
        if self._chat:
            path_text += (
                ". If CHAT2API_CONFIG is set externally for the supervised "
                "service, ai-manager edits a different file."
            )
        layout.addWidget(_label(path_text, self))

        self._validation_label = _label(NOT_VALIDATED, self)
        self._readonly_label = _label("", self)
        self._gate_label = _label("", self)
        self._auth_label = _label("", self)
        self._notice_label = _label("", self)
        for label in (
            self._validation_label,
            self._readonly_label,
            self._gate_label,
            self._auth_label,
            self._notice_label,
        ):
            layout.addWidget(label)
        if not self._chat:
            self._gate_label.hide()

        self._details_toggle = QToolButton(self)
        self._details_toggle.setText("Validator details")
        self._details_toggle.setCheckable(True)
        self._details = QPlainTextEdit(self)
        self._details.setReadOnly(True)
        self._details.hide()
        self._details_toggle.toggled.connect(self._details.setVisible)
        layout.addWidget(self._details_toggle)
        layout.addWidget(self._details)

        self._tabs = QTabWidget(self)
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        self._form = QWidget(scroll)
        self._form_layout = QVBoxLayout(self._form)
        scroll.setWidget(self._form)
        page_layout.addWidget(scroll, 1)

        footer = QFrame(page)
        footer.setObjectName("footerActionBar")
        actions = QHBoxLayout(footer)
        self._dirty_label = _label("", self)
        self._create_btn = QPushButton("Create from Example", self)
        self._create_btn.clicked.connect(self._create_from_example)
        self._review_btn = QPushButton("Review Changes", self)
        self._review_btn.clicked.connect(self._review_changes)
        self._save_only_btn = QPushButton("Save Config Only", self)
        self._save_only_btn.clicked.connect(lambda: self._emit_save(False))
        self._save_restart_btn = QPushButton("Save and Restart", self)
        self._save_restart_btn.clicked.connect(lambda: self._emit_save(True))
        for widget in (
            self._dirty_label,
            self._create_btn,
            self._review_btn,
            self._save_only_btn,
            self._save_restart_btn,
        ):
            actions.addWidget(widget)
        page_layout.addWidget(footer)

        self._log_view_widget = LogViewWidget(self.app_meta.id, self)
        self._tabs.addTab(page, "Configuration")
        self._tabs.addTab(self._log_view_widget, "Logs")
        layout.addWidget(self._tabs, 1)

        self.set_launcher_gate(None)

    @property
    def log_view(self) -> LogViewWidget:
        """The embedded log page; its service id is this app's id."""
        return self._log_view_widget

    # -- loading --------------------------------------------------------------

    def load_config(self, config: StructuredDoc) -> None:
        """Install ``config`` as baseline and build the declared form."""
        if config.kind != self._kind:
            raise ConfigError(
                f"Cannot load a {config.kind} configuration into the "
                f"{self._kind} view."
            )
        self._baseline = copy.deepcopy(config)
        self._model = StructuredEditorModel(config)
        self._load_failed = False
        self._fields = {}
        self._option_fields = {}
        self._row_issue_widgets = {}
        self._raw_toggles = {}
        self._expanded_row_id = None
        self._expanded_identity = None
        self._details.clear()
        self._details_toggle.setChecked(False)
        self._clear(self._form_layout)
        self._build_form(config)
        self._form_layout.addStretch(1)
        self._validation_label.setText(NOT_VALIDATED)
        self._notice_label.setText("")
        self._auth_label.setText("")
        self._readonly_label.setText(_reason_text(config.read_only_reasons))
        if self._chat:
            self._provider_warning.setText("")
        if "yaml-anchors-aliases" in config.read_only_reasons:
            self._details.setPlainText(config.raw_bytes.decode("utf-8", errors="replace"))
        port, issue = self._configured_port(config)
        self._title_label.setText(f"{self.app_meta.display_name} (Port {port})")
        if issue is not None:
            self.show_field_issues((issue,))
        self._controls()

    def _configured_port(
        self, config: StructuredDoc
    ) -> tuple[int, FieldIssue | None]:
        """The configured (loaded or committed) port, never the edited draft.

        An invalid stored port is reported and shown as the metadata default;
        it is never coerced into a writable value.
        """
        if self._chat:
            server = config.doc.get("server")
            values = server if isinstance(server, Mapping) else {}
            address: tuple[str, ...] = ("server", "port")
        else:
            values = config.doc
            address = ("port",)
        port = values.get("port", self.app_meta.default_port)
        if type(port) is not int or not 1 <= port <= 65535:
            return self.app_meta.default_port, FieldIssue(
                address, "Port must be an integer from 1 to 65535."
            )
        return port, None

    def _build_form(self, config: StructuredDoc) -> None:
        fields = SERVER_FIELDS if self._chat else FILE_BRIDGE_FIELDS
        group = QGroupBox(
            escape_mnemonic("Server" if self._chat else "Save Location & Server"),
            self._form,
        )
        form = QFormLayout(group)
        tree = self._model.tree
        if self._chat:
            server = tree.get("server")
            values = server if isinstance(server, Mapping) else {}
        else:
            values = tree
        defaults = (
            {"host": "127.0.0.1", "port": 8000, "auth_token_env": "CHAT2API_TOKEN"}
            if self._chat
            else {"save_root": "~", "max_text_bytes": 1_048_576, "port": 8964}
        )
        for spec in fields:
            address = ("server", spec.key) if self._chat else (spec.key,)
            field = PresenceControl(
                spec.control,
                spec.key in values,
                values.get(spec.key),
                default=defaults[spec.key],
                parent=group,
            )
            field.setToolTip(spec.annotation)
            field.written.connect(
                lambda present, value, at=address: self._on_field_changed(
                    at, present, value
                )
            )
            self._fields[address] = field
            text = spec.label + (f" ({spec.annotation})" if spec.annotation else "")
            form.addRow(_label(text, group), field)
        self._form_layout.addWidget(group)
        if self._chat:
            self._build_models_group()

    def _build_models_group(self) -> None:
        group = QGroupBox("Models", self._form)
        box = QVBoxLayout(group)
        self._table = QTableWidget(0, 4, group)
        self._table.setHorizontalHeaderLabels(["Name", "Provider", "Options", "Secrets"])
        self._table.cellChanged.connect(self._name_changed)
        box.addWidget(self._table)
        add = QPushButton("Add Model", group)
        add.clicked.connect(self._add_model)
        box.addWidget(add)
        self._provider_warning = _label("", group)
        box.addWidget(self._provider_warning)
        self._options_box = QWidget(group)
        self._options_layout = QVBoxLayout(self._options_box)
        box.addWidget(self._options_box)
        self._form_layout.addWidget(group)
        self._populate_rows()

    # -- models table ---------------------------------------------------------

    def _populate_rows(self) -> None:
        self._row_issue_widgets = {}
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._model.rows))
        for index, row in enumerate(self._model.rows):
            name = QTableWidgetItem(row.name)
            name.setData(Qt.ItemDataRole.UserRole, row.id)
            self._table.setItem(index, 0, name)
            providers = QComboBox(self._table)
            providers.addItem("")
            providers.addItems(list(PROVIDER_OPTIONS))
            provider = row.route.get("provider")
            if provider and provider not in PROVIDER_OPTIONS:
                providers.addItem(str(provider))
            providers.setCurrentText(provider or "")
            providers.currentTextChanged.connect(
                lambda value, uid=row.id: self._on_provider_changed(uid, value)
            )
            self._table.setCellWidget(index, 1, providers)
            expand = QToolButton(self._table)
            expand.setText("Options")
            expand.clicked.connect(
                lambda checked=False, uid=row.id: self._expand_model(uid)
            )
            self._table.setCellWidget(index, 2, expand)
            self._row_issue_widgets[("models", row.name)] = expand
            self._row_issue_widgets[("models", row.name, "provider")] = providers
            self._table.setCellWidget(index, 3, _label(self._secret_count(row), self._table))
        self._table.blockSignals(False)

    @staticmethod
    def _secret_count(row) -> str:
        options = row.route.get("options")
        present = options if isinstance(options, Mapping) else {}
        return f"{len(SECRET_OPTION_KEYS.intersection(present))} present"

    def _row_index(self, row_id: int) -> int:
        for index in range(self._table.rowCount()):
            item = self._table.item(index, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == row_id:
                return index
        return -1

    def _name_changed(self, row: int, column: int) -> None:
        if column != 0 or self._model is None:
            return
        item = self._table.item(row, 0)
        if item is None:
            return
        row_id = item.data(Qt.ItemDataRole.UserRole)
        previous = self._model.row(row_id).name
        if previous == item.text():
            return
        self._model.rename_model(row_id, item.text())
        # Widget addresses embed the model name; keep issue highlighting and
        # expanded option fields reachable under the new spelling.
        self._rekey(self._option_fields, previous, item.text())
        self._rekey(self._row_issue_widgets, previous, item.text())
        if self._expanded_row_id == row_id and self._expanded_identity is not None:
            self._expanded_identity = (self._expanded_identity[0], item.text())
        self._on_changed()

    @staticmethod
    def _rekey(mapping: dict, previous: str, current: str) -> None:
        moved = {}
        for key, value in mapping.items():
            if len(key) > 1 and key[0] == "models" and key[1] == previous:
                key = ("models", current) + key[2:]
            moved[key] = value
        mapping.clear()
        mapping.update(moved)

    def _add_model(self, checked: bool = False) -> None:
        if self._model is None:
            return
        row_id = self._model.add_model()
        self._populate_rows()
        self._expand_model(row_id)
        self._on_changed()

    def _remove_model(self, row_id: int) -> None:
        if self._model is None:
            return
        self._model.remove_model(row_id)
        self._populate_rows()
        self._clear(self._options_layout)
        self._option_fields = {}
        self._raw_toggles = {}
        self._expanded_row_id = None
        self._expanded_identity = None
        self._on_changed()

    def _expand_model(self, row_id: int) -> None:
        row = self._model.row(row_id)
        self._expanded_row_id = row_id
        self._expanded_identity = (row.original_name, row.name)
        self._row_issue_widgets = {
            key: widget
            for key, widget in self._row_issue_widgets.items()
            if not (len(key) == 3 and key[-1] == "options")
        }
        self._clear(self._options_layout)
        self._option_fields = {}
        self._raw_toggles = {}
        panel = QWidget(self._options_box)
        form = QFormLayout(panel)
        options = row.route.get("options")
        options = options if isinstance(options, Mapping) else {}
        specs = list(PROVIDER_OPTIONS.get(row.route.get("provider"), ()))
        known = {spec.key for spec in specs}
        # A secret that survives a provider switch keeps its own masked field.
        specs += [
            OptionSpec(key, "secret")
            for key in options
            if key in SECRET_OPTION_KEYS and key not in known
        ]
        for spec in specs:
            field = PresenceControl(
                spec.control, spec.key in options, options.get(spec.key), parent=panel
            )
            field.written.connect(
                lambda present, value, uid=row_id, key=spec.key: self._option_changed(
                    uid, key, present, value
                )
            )
            self._option_fields[("models", row.name, "options", spec.key)] = field
            form.addRow(_label(spec.key, panel), field)
        raw_toggle = QToolButton(panel)
        raw_toggle.setText("Raw options")
        raw_toggle.setCheckable(True)
        raw = QPlainTextEdit(panel)
        raw_address = ("models", row.name, "options")
        self._row_issue_widgets[raw_address] = raw
        self._raw_toggles[raw_address] = raw_toggle
        raw.setPlainText(
            row.raw_text
            if row.raw_text is not None
            else json.dumps(
                self._model.raw_options(row_id), indent=2, ensure_ascii=False
            )
        )
        raw.hide()
        if row.raw_text is not None:
            raw_toggle.setChecked(True)
            raw.show()
        raw_toggle.toggled.connect(raw.setVisible)
        raw.textChanged.connect(
            lambda uid=row_id, edit=raw: self._on_raw_options_changed(
                uid, edit.toPlainText()
            )
        )
        form.addRow(raw_toggle)
        form.addRow(raw)
        remove = QPushButton("Remove Model", panel)
        remove.clicked.connect(lambda checked=False, uid=row_id: self._remove_model(uid))
        form.addRow(remove)
        self._options_layout.addWidget(panel)

    def _on_provider_changed(self, row_id: int, provider: str) -> None:
        if self._model is None:
            return
        self._model.set_provider(row_id, provider)
        self._provider_warning.setText(PROVIDER_WARNING)
        # Provider/secret classification moved; rebuild the derived option
        # fields and refresh the derived secret count without touching values.
        self._expand_model(row_id)
        index = self._row_index(row_id)
        if index >= 0:
            self._table.cellWidget(index, 3).setText(
                self._secret_count(self._model.row(row_id))
            )
        self._on_changed()

    def _option_changed(self, row_id: int, key: str, present: bool, value: Any) -> None:
        self._model.set_option(row_id, key, present=present, value=value)
        index = self._row_index(row_id)
        if index >= 0:
            self._table.cellWidget(index, 3).setText(
                self._secret_count(self._model.row(row_id))
            )
        self._on_changed()

    def _on_raw_options_changed(self, row_id: int, text: str) -> None:
        self._model.set_raw_options(row_id, text)
        self._on_changed()

    def _on_field_changed(self, address, present: bool, value: Any) -> None:
        if self._model is None:
            return
        self._model.set_field(address, present=present, value=value)
        self._on_changed()

    # -- draft and edits ------------------------------------------------------

    def _on_changed(self) -> None:
        try:
            draft = self.get_current_draft()
        except ConfigError as exc:
            self.show_config_error(str(exc))
            return
        try:
            effective_mutations(draft)
        except ConfigValidationError as exc:
            self.show_field_issues(exc.issues)
        else:
            self.show_field_issues(())
        if (
            self._notice_label.text() == GATE_BYPASS
            and not self._has_listener_change(draft)
        ):
            # Reverting the listener edit makes the bypass notice stale.
            self._notice_label.setText("")
        self.config_changed.emit(self.app_meta.id, draft)

    def _has_listener_change(self, draft: StructuredDoc) -> bool:
        """Whether the draft writes chat2api host or port."""
        if not self._chat:
            return False
        try:
            mutations = effective_mutations(draft)
        except ConfigError:
            return False
        return any(
            mutation.address[: len(address)] == address
            for mutation in mutations
            for address in LISTENER_ADDRESSES
        )

    def get_current_draft(self) -> StructuredDoc:
        if self._model is None:
            raise ConfigError(UNINITIALIZED_SAVE)
        return self._model.draft()

    def adopt_saved_baseline(
        self, config: StructuredDoc, *, preserve_draft: bool
    ) -> None:
        """Install a committed snapshot without discarding a dirty draft.

        With ``preserve_draft`` the retained mutations are rebased onto the new
        baseline so a later save still describes exactly the user's edits, and
        the widgets keep their current values. No disk read happens here.
        """
        if not preserve_draft:
            self.load_config(config)
            return
        try:
            draft = self.get_current_draft()
        except ConfigError:
            self.load_config(config)
            return
        rebased = type(config)(
            kind=config.kind,
            path=config.path,
            resolved_path=config.resolved_path,
            doc=config.doc,
            raw_bytes=config.raw_bytes,
            raw_sha256=config.raw_sha256,
            existed=config.existed,
            mode=config.mode,
            read_only_reasons=config.read_only_reasons,
            mutations=draft.mutations,
            raw_option_edits=dict(draft.raw_option_edits),
            input_issues=draft.input_issues,
            create_requested=config.create_requested,
        )
        self._baseline = copy.deepcopy(config)
        self._model = StructuredEditorModel(rebased)
        self._load_failed = False
        self._readonly_label.setText(_reason_text(config.read_only_reasons))
        if self._chat:
            self._populate_rows()
            self._clear(self._options_layout)
            self._option_fields = {}
            self._raw_toggles = {}
            self._expanded_row_id = self._match_expanded_row()
            if self._expanded_row_id is not None:
                self._expand_model(self._expanded_row_id)
            self._provider_warning.setText("")
        port, issue = self._configured_port(config)
        self._title_label.setText(f"{self.app_meta.display_name} (Port {port})")
        if issue is not None:
            self.show_field_issues((issue,))
        self._controls()

    # -- save and review ------------------------------------------------------

    def _emit_save(self, restart: bool) -> None:
        if self._saving:
            return
        try:
            draft = self.get_current_draft()
        except ConfigError as exc:
            self.show_config_error(str(exc))
            return
        if not self._listener_changes_emittable(draft):
            return
        self.save_requested.emit(self.app_meta.id, draft, restart)

    def _listener_changes_emittable(self, draft: StructuredDoc) -> bool:
        """Refuse host/port saves while the launcher probe has not passed."""
        gate_open = self._gate is not None and self._gate.passed
        if not gate_open and self._has_listener_change(draft):
            self.show_config_error(GATE_BYPASS)
            return False
        if self._notice_label.text() == GATE_BYPASS:
            # A reverted listener edit is savable again; drop only our own notice.
            self._notice_label.setText("")
        return True

    def _review_changes(self) -> None:
        try:
            draft = self.get_current_draft()
            before = self._baseline.raw_bytes if self._baseline is not None else b""
            ReviewChangesDialog(
                before, render(draft.kind, draft), draft.path, self
            ).exec()
        except ConfigError as exc:
            self.show_config_error(str(exc))

    def _create_from_example(self) -> None:
        try:
            path = Path(self.app_meta.relative_path / self.app_meta.config_file_name)
            draft = load_example(
                self._kind,
                path,
                Path(self.app_meta.relative_path / self.app_meta.example_config_file_name),
            )
        except MissingExampleError as exc:
            self.show_config_error(exc.detail)
        except ConfigError as exc:
            self.show_config_error(str(exc))
        else:
            self.load_config(draft)
            self.config_changed.emit(self.app_meta.id, draft)

    # -- status surface -------------------------------------------------------

    def show_load_error(self, message, reason="load-error") -> None:
        """Report a failed load and disable editing, keeping header and logs."""
        self._load_failed = True
        lines: list[str] = []
        if message:
            lines.append(str(message))
        explanation = READ_ONLY_MESSAGES.get(reason)
        if explanation is not None and not any(explanation in line for line in lines):
            lines.append(explanation)
        if not lines:
            lines.append(READ_ONLY_MESSAGES["load-error"])
        self._readonly_label.setText("\n".join(lines))
        self._controls()

    def show_config_error(self, message, detail=None) -> None:
        self._notice_label.setText(message)
        if detail is not None:
            # Omitted detail preserves the validator output already displayed.
            self._details.setPlainText(detail)
        if detail:
            self._details_toggle.setChecked(True)

    def show_field_issues(self, issues: tuple[FieldIssue, ...]) -> None:
        fields: dict[tuple[str, ...], QWidget] = {
            **self._row_issue_widgets,
            **self._fields,
            **self._option_fields,
        }
        for field in fields.values():
            field.setStyleSheet("")
        highlighted: set[tuple[str, ...]] = set()
        for issue in issues:
            address = self._resolve_address(fields, issue.address)
            if address is None:
                continue
            highlighted.add(address)
            field = fields[address]
            field.setStyleSheet("border: 1px solid #ef4444;")
            field.setToolTip(issue.message)
        for address, toggle in self._raw_toggles.items():
            if address in highlighted:
                # A raw-options error is only visible when its editor is shown.
                toggle.setChecked(True)
        if issues:
            messages = "\n".join(dict.fromkeys(issue.message for issue in issues))
            self._notice_label.setText(f"{INVALID_INPUT}\n{messages}")
        elif self._notice_label.text().startswith(INVALID_INPUT):
            self._notice_label.setText("")

    @staticmethod
    def _resolve_address(
        fields: Mapping[tuple[str, ...], QWidget], address: tuple[str, ...]
    ) -> tuple[str, ...] | None:
        """The exact widget address for an issue, else its deepest ancestor."""
        if address in fields:
            return address
        prefixes = [prefix for prefix in fields if address[: len(prefix)] == prefix]
        return max(prefixes, key=len) if prefixes else None

    def _match_expanded_row(self) -> int | None:
        if self._expanded_identity is None or self._model is None:
            return None
        for row in self._model.rows:
            if (row.original_name, row.name) == self._expanded_identity:
                return row.id
        return None

    def set_validation_result(self, result: ValidationResult) -> None:
        self._validation_label.setText(result.notice)
        self._details.setPlainText(result.detail)

    def show_auth_warnings(self, warnings: tuple[str, ...]) -> None:
        self._auth_label.setText("\n".join(warnings))

    def set_launcher_gate(self, result: LauncherProbeResult | None) -> None:
        self._gate = result
        if not self._chat:
            # A file-bridge listener is not gated by the chat2api launcher.
            self._gate_label.hide()
            self._controls()
            return
        if result is None:
            self._gate_label.setText(GATE_PENDING)
        elif result.passed:
            self._gate_label.setText(GATE_PASSED)
        else:
            self._gate_label.setText(GATE_FAILED)
            if result.detail or result.stderr:
                joined = result.detail + ("\n" if result.detail and result.stderr else "")
                self._details.setPlainText(joined + (result.stderr or ""))
                self._details_toggle.setChecked(True)
        self._controls()

    def set_save_in_progress(self, saving: bool) -> None:
        self._saving = saving
        if saving:
            self._notice_label.setText(SAVING)
        elif self._notice_label.text() == SAVING:
            self._notice_label.setText("")
        self._controls()

    def update_service_status(self, status: ServiceStatus) -> None:
        if status.log_path:
            self._known_log_path = str(status.log_path)
        self._log_view_widget.set_log_path(
            self._known_log_path or str(default_log_path(self.app_meta.id))
        )
        self._log_view_widget.set_service_state(status.state)
        self._status_badge.set_status(status.state, status.pid)

    # -- enablement -----------------------------------------------------------

    def _document(self) -> StructuredDoc | None:
        return self._model.baseline if self._model is not None else None

    def _writable(self) -> bool:
        doc = self._document()
        return bool(
            doc is not None
            and not self._load_failed
            and not doc.read_only_reasons
            and (doc.existed or doc.create_requested)
        )

    def _controls(self) -> None:
        writable = self._writable()
        self._form.setEnabled(bool(writable and not self._saving))
        for widget in (self._save_only_btn, self._save_restart_btn, self._review_btn):
            widget.setEnabled(bool(writable and not self._saving))
        doc = self._document()
        self._create_btn.setVisible(bool(doc is not None and not doc.existed and not doc.create_requested))
        self._create_btn.setEnabled(not self._saving and not self._load_failed)
        if self._chat:
            gate_open = self._gate is not None and self._gate.passed
            for key in ("host", "port"):
                field = self._fields.get(("server", key))
                if field is not None:
                    field.setEnabled(bool(writable and not self._saving and gate_open))
        if doc is not None and not doc.existed and not doc.create_requested:
            # Nothing to edit yet: the target does not exist and no draft was
            # created from the example, so say so instead of a blank form.
            self._readonly_label.setText(MISSING_TARGET)

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
