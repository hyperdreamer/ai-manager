from PyQt6.QtWidgets import QApplication, QLineEdit
from ai_manager.config.models import ServiceRunState, ThemeMode
from ai_manager.ui.theme import get_stylesheet
from ai_manager.ui.widgets.api_key_input import ApiKeyInputWidget
from ai_manager.ui.widgets.model_combo import ModelComboBox
from ai_manager.ui.widgets.status_badge import StatusBadge


def test_theme_stylesheets():
    dark_css = get_stylesheet(ThemeMode.DARK)
    light_css = get_stylesheet(ThemeMode.LIGHT)
    assert "background-color: #18181f" in dark_css
    assert "background-color: #ffffff" in light_css


def test_status_badge(qtbot):
    badge = StatusBadge()
    qtbot.addWidget(badge)
    badge.set_status(ServiceRunState.RUNNING, pid=9999)
    assert "Running (PID 9999)" in badge._text_label.text()

    badge.set_status(ServiceRunState.STOPPED)
    assert "Stopped" in badge._text_label.text()


def test_model_combo(qtbot):
    combo = ModelComboBox()
    qtbot.addWidget(combo)
    combo.set_models(["gemini-flash-high", "deepseek-flash"], current="deepseek-flash")
    assert combo.currentText() == "deepseek-flash"
    assert combo.count() == 2


def test_api_key_input(qtbot):
    widget = ApiKeyInputWidget()
    qtbot.addWidget(widget)
    widget.setText("sk-plaintext-key")
    assert widget._line_edit.echoMode() == QLineEdit.EchoMode.Password

    # Toggle reveal
    widget._toggle_echo()
    assert widget._line_edit.echoMode() == QLineEdit.EchoMode.Normal
    assert widget._toggle_btn.text() == "🔒"
