import pytest
from PyQt6.QtCore import QPoint, QSizeF, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ai_manager import __version__
from ai_manager.ui.about_dialog import AboutDialog
from tests.test_mnemonic import find_unescaped_ampersand_sinks


TEXT_LABEL_NAMES = (
    "aboutNameLabel",
    "aboutVersionLabel",
    "aboutDescriptionLabel",
)


def _icon_label(dialog):
    remaining = [
        label for label in dialog.findChildren(QLabel)
        if label.objectName() not in TEXT_LABEL_NAMES
    ]
    assert len(remaining) == 1
    return remaining[0]


@pytest.fixture
def dialog(qtbot):
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    return dlg


def test_about_dialog_content_and_object_names(dialog):
    assert dialog.windowTitle() == "About ai-manager"
    expected = {
        "aboutNameLabel": "ai-manager",
        "aboutVersionLabel": f"Version {__version__}",
        "aboutDescriptionLabel":
            "Desktop administration GUI for local AI backends",
    }
    for name, text in expected.items():
        assert len(dialog.findChildren(QLabel, name)) == 1
        label = dialog.findChild(QLabel, name)
        assert label.text() == text
        assert label.textFormat() == Qt.TextFormat.PlainText
    labels = dialog.findChildren(QLabel)
    assert len(labels) == 4
    assert all(label.buddy() is None for label in labels)
    icon = _icon_label(dialog)
    assert icon.text() == ""
    pixmap = icon.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.deviceIndependentSize() == QSizeF(48, 48)


def test_about_dialog_hierarchy_and_geometry(dialog):
    outer = dialog.layout()
    assert isinstance(outer, QVBoxLayout)
    assert outer.count() == 3
    header = outer.itemAt(0).layout()
    assert isinstance(header, QHBoxLayout)
    assert header.count() == 2
    assert header.itemAt(0).widget() is _icon_label(dialog)
    text_layout = header.itemAt(1).layout()
    assert isinstance(text_layout, QVBoxLayout)
    assert text_layout.count() == 2
    assert text_layout.itemAt(0).widget() is dialog.findChild(
        QLabel, "aboutNameLabel"
    )
    assert text_layout.itemAt(1).widget() is dialog.findChild(
        QLabel, "aboutVersionLabel"
    )
    description = dialog.findChild(QLabel, "aboutDescriptionLabel")
    assert outer.itemAt(1).widget() is description
    boxes = dialog.findChildren(QDialogButtonBox)
    assert len(boxes) == 1
    box = boxes[0]
    assert outer.itemAt(2).widget() is box
    assert all(
        widget.parentWidget() is dialog
        for widget in [*dialog.findChildren(QLabel), box]
    )
    assert dialog.minimumWidth() == dialog.maximumWidth() == dialog.width() == 360
    assert dialog.sizeHint().width() == 360
    assert dialog.minimumHeight() < dialog.maximumHeight()
    assert description.wordWrap() is False
    assert dialog.isModal() is True
    assert dialog.isSizeGripEnabled() is False
    assert box.orientation() == Qt.Orientation.Horizontal
    dialog.show()
    outer.activate()
    box.layout().activate()
    QApplication.processEvents()
    assert box.buttons()
    for button in box.buttons():
        assert button.mapTo(box, QPoint(0, 0)).x() > box.width() / 2


def test_about_dialog_uses_color_icon(qtbot, monkeypatch):
    sentinel = QPixmap(1, 1)
    sentinel.fill(QColor("magenta"))
    calls = []

    def sentinel_icon():
        calls.append(True)
        return QIcon(sentinel)

    monkeypatch.setattr("ai_manager.ui.about_dialog.color_icon", sentinel_icon)
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    assert calls == [True]
    pixmap = _icon_label(dlg).pixmap()
    assert pixmap is not None and not pixmap.isNull()
    image = pixmap.toImage()
    assert image.pixelColor(image.width() // 2, image.height() // 2) == QColor(
        "magenta"
    )


def test_about_dialog_version_propagates_from_source(qtbot, monkeypatch):
    monkeypatch.setattr("ai_manager.ui.about_dialog.__version__", "9.8.7")
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    assert dlg.findChild(QLabel, "aboutVersionLabel").text() == "Version 9.8.7"


def test_about_dialog_parent_is_supplied_widget(qtbot):
    sentinel_widget = QWidget()
    qtbot.addWidget(sentinel_widget)
    dlg = AboutDialog(parent=sentinel_widget)
    qtbot.addWidget(dlg)
    assert dlg.parentWidget() is sentinel_widget


@pytest.mark.parametrize("version", ["9.8.7", "0.2.0rc1"])
def test_about_dialog_accepts_injected_version(qtbot, version):
    dlg = AboutDialog(version=version)
    qtbot.addWidget(dlg)
    assert dlg.findChild(QLabel, "aboutVersionLabel").text() == f"Version {version}"


def test_close_button_accepts_dialog(dialog):
    box = dialog.findChild(QDialogButtonBox)
    close_button = box.button(QDialogButtonBox.StandardButton.Close)
    assert close_button is not None
    assert box.standardButtons() == QDialogButtonBox.StandardButton.Close
    assert box.buttons() == [close_button]
    assert close_button.text() == "Close"
    assert box.buttonRole(close_button) == QDialogButtonBox.ButtonRole.RejectRole
    QTimer.singleShot(0, close_button.click)
    assert dialog.exec() == QDialog.DialogCode.Accepted
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_about_dialog_has_no_unescaped_ampersands(dialog):
    box = dialog.findChild(QDialogButtonBox)
    assert box.button(QDialogButtonBox.StandardButton.Close) is not None
    assert find_unescaped_ampersand_sinks(dialog) == []
