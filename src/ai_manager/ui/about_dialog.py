"""Read-only application identity and version dialog."""

from typing import Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ai_manager import __version__
from ai_manager.ui.icons import color_icon


class AboutDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        version: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self.version = __version__ if version is None else version
        self.setWindowTitle("About ai-manager")
        self.setModal(True)
        self.setFixedWidth(360)
        self.setSizeGripEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        header = QHBoxLayout()
        icon_label = QLabel(self)
        icon_label.setPixmap(color_icon().pixmap(48, 48))
        header.addWidget(icon_label)

        text_layout = QVBoxLayout()
        name_label = QLabel("ai-manager", self)
        name_label.setObjectName("aboutNameLabel")
        name_label.setTextFormat(Qt.TextFormat.PlainText)
        version_label = QLabel(f"Version {self.version}", self)
        version_label.setObjectName("aboutVersionLabel")
        version_label.setTextFormat(Qt.TextFormat.PlainText)
        text_layout.addWidget(name_label)
        text_layout.addWidget(version_label)
        header.addLayout(text_layout)
        layout.addLayout(header)

        description = QLabel(
            "Desktop administration GUI for local AI backends", self
        )
        description.setObjectName("aboutDescriptionLabel")
        description.setTextFormat(Qt.TextFormat.PlainText)
        description.setWordWrap(False)
        layout.addWidget(description)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            Qt.Orientation.Horizontal,
            self,
        )
        button_box.setCenterButtons(False)
        button_box.button(QDialogButtonBox.StandardButton.Close).clicked.connect(
            self.accept
        )
        layout.addWidget(button_box)

    def sizeHint(self) -> QSize:
        return QSize(360, super().sizeHint().height())
