from typing import Optional
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget
from ai_manager.utils.env_resolver import get_env_var_status


class ApiKeyInputWidget(QWidget):
    """API Key input with reveal toggle and environment variable validation."""

    textChanged = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._line_edit = QLineEdit(self)
        self._line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._line_edit.textChanged.connect(self._on_text_changed)

        self._toggle_btn = QPushButton("👁️", self)
        self._toggle_btn.setFixedWidth(36)
        self._toggle_btn.setToolTip("Show / Hide API Key")
        self._toggle_btn.clicked.connect(self._toggle_echo)

        self._status_label = QLabel(self)
        self._status_label.setStyleSheet("font-size: 11px; color: #9ca3af;")

        layout.addWidget(self._line_edit, stretch=2)
        layout.addWidget(self._toggle_btn)
        layout.addWidget(self._status_label, stretch=1)

    def text(self) -> str:
        return self._line_edit.text()

    def setText(self, text: str) -> None:
        self._line_edit.setText(text)
        self._update_status(text)

    def _toggle_echo(self) -> None:
        if self._line_edit.echoMode() == QLineEdit.EchoMode.Password:
            self._line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._toggle_btn.setText("🔒")
        else:
            self._line_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._toggle_btn.setText("👁️")

    def _on_text_changed(self, text: str) -> None:
        self._update_status(text)
        self.textChanged.emit(text)

    def _update_status(self, text: str) -> None:
        is_ok, msg = get_env_var_status(text)
        self._status_label.setText(msg)
        if not is_ok:
            self._status_label.setStyleSheet("font-size: 11px; color: #f59e0b;")
        else:
            self._status_label.setStyleSheet("font-size: 11px; color: #10b981;")
