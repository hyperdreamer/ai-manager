from typing import Optional
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget
from ai_manager.config.models import ServiceRunState


class StatusBadge(QWidget):
    """Badge widget displaying status circle and label."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._dot_label = QLabel(self)
        self._dot_label.setFixedSize(10, 10)

        self._text_label = QLabel("Unknown", self)
        self._text_label.setObjectName("statusBadgeStopped")

        layout.addWidget(self._dot_label)
        layout.addWidget(self._text_label)

    def set_status(self, state: ServiceRunState, pid: Optional[int] = None) -> None:
        if state == ServiceRunState.RUNNING:
            text = f"Running (PID {pid})" if pid else "Running"
            self._text_label.setText(text)
            self._text_label.setObjectName("statusBadgeRunning")
            self._dot_label.setStyleSheet("background-color: #10b981; border-radius: 5px;")
        elif state == ServiceRunState.STOPPED:
            self._text_label.setText("Stopped")
            self._text_label.setObjectName("statusBadgeStopped")
            self._dot_label.setStyleSheet("background-color: #9ca3af; border-radius: 5px;")
        elif state == ServiceRunState.TRANSITIONING:
            self._text_label.setText("Restarting...")
            self._text_label.setObjectName("statusBadgeTransitioning")
            self._dot_label.setStyleSheet("background-color: #f59e0b; border-radius: 5px;")
        else:
            self._text_label.setText("Unknown")
            self._text_label.setObjectName("statusBadgeStopped")
            self._dot_label.setStyleSheet("background-color: #6b7280; border-radius: 5px;")

        # Force style re-evaluation
        self._text_label.style().unpolish(self._text_label)
        self._text_label.style().polish(self._text_label)
