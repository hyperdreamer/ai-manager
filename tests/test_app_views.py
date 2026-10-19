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


def test_llm_adapter_signals_payload_object_and_common_surface(qtbot):
    """Task 11's deferred item: both views must be storable in one dict.

    ``save_requested`` and ``config_changed`` carry ``object`` so a single Qt
    connection signature serves the LLM and structured adapters alike.
    """
    from PyQt6.QtCore import QMetaMethod

    detail = AppDetailView(get_managed_apps(Path("/tmp"))["ai-grammar"])
    qtbot.addWidget(detail)
    meta = detail.metaObject()
    declared = {}
    for index in range(meta.methodOffset(), meta.methodCount()):
        method = meta.method(index)
        if method.methodType() == QMetaMethod.MethodType.Signal:
            declared[bytes(method.name()).decode()] = bytes(
                method.methodSignature()
            ).decode()
    assert declared["save_requested"] == "save_requested(QString,PyQt_PyObject,bool)"
    assert declared["config_changed"] == "config_changed(QString,PyQt_PyObject)"
    for name in ("adopt_saved_baseline", "show_config_error", "set_save_in_progress"):
        assert callable(getattr(detail, name))


def test_llm_adopt_saved_baseline_rebases_with_and_without_draft(qtbot):
    detail = AppDetailView(get_managed_apps(Path("/tmp"))["textkit"])
    qtbot.addWidget(detail)
    detail.load_config(AppAIConfig(api_base="http://127.0.0.1:8000", model="saved"))
    detail._model_combo.setEditText("user-typed")
    committed = AppAIConfig(api_base="http://127.0.0.1:8123", model="saved")

    detail.adopt_saved_baseline(committed, preserve_draft=True)
    # The baseline moves; the widget values and the draft do not.
    assert detail._current_config == committed
    assert detail.get_current_draft() == AppAIConfig(
        api_base="http://127.0.0.1:8000", model="user-typed"
    )

    detail.adopt_saved_baseline(committed, preserve_draft=False)
    assert detail._current_config == committed
    assert detail.get_current_draft() == committed


def test_llm_show_config_error_displays_plain_text_detail(qtbot):
    from PyQt6.QtCore import Qt

    detail = AppDetailView(get_managed_apps(Path("/tmp"))["ai-grammar"])
    qtbot.addWidget(detail)
    assert detail._config_error_details.isHidden()
    detail.show_config_error("Rejected & <nothing> saved.", "<exact & stderr>\n")
    assert detail._config_error_label.text() == "Rejected & <nothing> saved."
    assert detail._config_error_label.textFormat() == Qt.TextFormat.PlainText
    assert detail._config_error_details.toPlainText() == "<exact & stderr>\n"
    assert not detail._config_error_details.isHidden()
    detail.show_config_error("Configuration saved.")
    assert detail._config_error_details.isHidden()


def test_llm_set_save_in_progress_disables_only_configuration_controls(qtbot):
    detail = AppDetailView(get_managed_apps(Path("/tmp"))["textkit"])
    qtbot.addWidget(detail)
    detail.set_save_in_progress(True)
    assert not detail._provider_group.isEnabled()
    assert not detail._model_group.isEnabled()
    assert not detail._save_only_btn.isEnabled()
    assert not detail._save_restart_btn.isEnabled()
    # Logs and Restart Service Only stay usable while a save is in flight.
    assert detail._tabs.isEnabled() and detail.log_view.isEnabled()
    assert detail._restart_btn.isEnabled()
    detail.set_save_in_progress(False)
    assert detail._provider_group.isEnabled() and detail._model_group.isEnabled()
    assert detail._save_only_btn.isEnabled() and detail._save_restart_btn.isEnabled()


def test_sidebar_shows_the_saved_port_and_survives_dirty_repaint(qtbot):
    apps = get_managed_apps(Path("/tmp"))
    sidebar = AppSidebar(apps)
    qtbot.addWidget(sidebar)

    sidebar.select_app("file-bridge")
    assert "Port 8964" in sidebar._list_widget.currentItem().text()

    sidebar.update_configured_port("file-bridge", 9100)
    assert "Port 9100" in sidebar._list_widget.currentItem().text()

    # Dirty and status repaints must not lose the cached saved port.
    sidebar.set_dirty("file-bridge", True)
    assert "Port 9100" in sidebar._list_widget.currentItem().text()
    sidebar.update_status(
        "file-bridge", ServiceStatus(service_id="file-bridge", state=ServiceRunState.RUNNING)
    )
    assert "Port 9100" in sidebar._list_widget.currentItem().text()

    # None forgets the cache and falls back to the metadata default.
    sidebar.update_configured_port("file-bridge", None)
    assert "Port 8964" in sidebar._list_widget.currentItem().text()


def test_sidebar_update_configured_port_validates_id_and_range(qtbot):
    import pytest

    apps = get_managed_apps(Path("/tmp"))
    sidebar = AppSidebar(apps)
    qtbot.addWidget(sidebar)
    with pytest.raises(KeyError):
        sidebar.update_configured_port("unknown", 8000)
    for bad in (True, False, 0, 65536, -1, 8000.0, "8000"):
        with pytest.raises(ValueError):
            sidebar.update_configured_port("chat2api", bad)
    sidebar.update_configured_port("chat2api", 1)
    sidebar.update_configured_port("chat2api", 65535)
    assert sidebar._configured_ports["chat2api"] == 65535
