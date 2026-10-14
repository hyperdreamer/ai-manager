from pathlib import Path

from PyQt6.QtWidgets import QFrame, QScrollArea, QTabWidget

from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.models import AppAIConfig, ServiceRunState, ServiceStatus
from ai_manager.ui.app_detail_view import AppDetailView
from ai_manager.ui.app_sidebar import AppSidebar


def test_app_sidebar(qtbot):
    apps = get_managed_apps(Path("/tmp"))
    sidebar = AppSidebar(apps)
    qtbot.addWidget(sidebar)

    assert sidebar.current_app_id() == "ai-grammar"

    # Select textkit
    sidebar.select_app("textkit")
    assert sidebar.current_app_id() == "textkit"

    # Set dirty
    sidebar.set_dirty("textkit", True)
    item = sidebar._list_widget.currentItem()
    assert "*" in item.text()

    # Update status
    sidebar.update_status(
        "textkit",
        ServiceStatus(
            service_id="textkit",
            state=ServiceRunState.RUNNING,
            pid=1234,
        ),
    )
    assert "●" in sidebar._list_widget.currentItem().text()


def test_app_detail_view(qtbot):
    apps = get_managed_apps(Path("/tmp"))
    meta_textkit = apps["textkit"]

    detail = AppDetailView(meta_textkit)
    qtbot.addWidget(detail)

    cfg = AppAIConfig(
        api_base="http://localhost:3000",
        api_key="sk-test",
        model="gemini-flash-high",
    )
    detail.load_config(cfg)

    draft = detail.get_current_draft()
    assert draft.api_base == "http://localhost:3000"
    assert draft.model == "gemini-flash-high"
    assert not draft.is_split_model

    # Toggle split models
    detail._split_chk.setChecked(True)
    detail._ocr_combo.setEditText("qwen-ocr")
    detail._text_combo.setEditText("deepseek-text")

    split_draft = detail.get_current_draft()
    assert split_draft.is_split_model is True
    assert split_draft.ocr_model == "qwen-ocr"
    assert split_draft.text_model == "deepseek-text"


def test_app_detail_has_configuration_and_logs_tabs(qtbot):
    detail = AppDetailView(get_managed_apps(Path("/tmp"))["textkit"])
    qtbot.addWidget(detail)
    tabs = detail.findChild(QTabWidget)
    assert tabs is not None
    assert tabs.count() == 2
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Configuration", "Logs"
    ]
    assert tabs.currentIndex() == 0
    config_page = tabs.widget(0)
    assert config_page.findChild(QScrollArea) is not None
    assert config_page.findChild(QFrame, "footerActionBar") is not None
    assert detail.log_view is tabs.widget(1)
    assert detail.log_view.service_id == "textkit"


def test_tab_switching_does_not_emit_config_changed_and_split_draft_survives(qtbot):
    detail = AppDetailView(get_managed_apps(Path("/tmp"))["textkit"])
    qtbot.addWidget(detail)
    changed = []
    detail.config_changed.connect(lambda *args: changed.append(args))
    tabs = detail.findChild(QTabWidget)
    tabs.setCurrentIndex(1)
    tabs.setCurrentIndex(0)
    assert changed == []
    detail._split_chk.setChecked(True)
    detail._ocr_combo.setEditText("qwen-ocr")
    detail._text_combo.setEditText("deepseek-text")
    draft = detail.get_current_draft()
    assert draft.is_split_model is True
    assert draft.ocr_model == "qwen-ocr"
    assert draft.text_model == "deepseek-text"


def test_explicit_log_path_is_remembered_over_fallback(monkeypatch, qtbot, tmp_path):
    apps = get_managed_apps(tmp_path)
    detail = AppDetailView(apps["textkit"])
    qtbot.addWidget(detail)
    fallback = tmp_path / "fallback.log"
    explicit = tmp_path / "reported.log"
    monkeypatch.setattr(
        "ai_manager.ui.app_detail_view.default_log_path",
        lambda service_id: fallback,
    )
    detail.update_service_status(
        ServiceStatus(service_id="textkit", state=ServiceRunState.UNKNOWN)
    )
    assert detail._known_log_path is None
    assert detail.log_view._reader.path == fallback
    detail.update_service_status(
        ServiceStatus(
            service_id="textkit", state=ServiceRunState.RUNNING,
            pid=42, log_path=str(explicit),
        )
    )
    assert detail._known_log_path == str(explicit)
    assert detail.log_view._reader.path == explicit
    detail.update_service_status(
        ServiceStatus(service_id="textkit", state=ServiceRunState.STOPPED)
    )
    assert detail._known_log_path == str(explicit)
    assert detail.log_view._reader.path == explicit


def test_update_service_status_updates_log_state_and_header_without_config_signal(qtbot):
    detail = AppDetailView(get_managed_apps(Path("/tmp"))["ai-grammar"])
    qtbot.addWidget(detail)
    detail.update_service_status(
        ServiceStatus(service_id="ai-grammar", state=ServiceRunState.TRANSITIONING, pid=7)
    )
    assert detail.log_view._service_state_label.text() == "service restarting"
    assert "Restarting" in detail._status_badge._text_label.text()
    assert detail._known_log_path is None
