from pathlib import Path

import pytest
from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QTabWidget

from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.models import AppAIConfig, ServiceRunState, ServiceStatus
from ai_manager.config.protocols import ENDPOINT_VALUES
from ai_manager.services.protocol_capability import ProtocolSupport, ProtocolSupportStatus
from tests.endpoint_helpers import meta_for, snapshot
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
    detail.load_config(snapshot(cfg))

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
    detail.load_config(snapshot(AppAIConfig(api_base="http://127.0.0.1:8000", model="saved")))
    detail._model_combo.setEditText("user-typed")
    committed = AppAIConfig(api_base="http://127.0.0.1:8123", model="saved")

    detail.adopt_saved_baseline(snapshot(committed), preserve_draft=True)
    # The baseline moves; the widget values and the draft do not.
    assert detail._current_config == committed
    assert detail.get_current_draft() == AppAIConfig(
        api_base="http://127.0.0.1:8000", model="user-typed"
    )

    detail.adopt_saved_baseline(snapshot(committed), preserve_draft=False)
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
    detail.load_config(snapshot())
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


def test_sidebar_saved_port_strictness_and_llm_baseline_adoption(qtbot, tmp_path):
    import pytest

    apps = get_managed_apps(tmp_path)
    sidebar = AppSidebar(apps)
    qtbot.addWidget(sidebar)
    assert sidebar._list_widget.count() == 5
    sidebar.update_configured_port("chat2api", 8123)
    sidebar.select_app("chat2api")
    sidebar.set_dirty("chat2api", True)
    assert "Port 8123" in sidebar._list_widget.currentItem().text()
    sidebar.update_configured_port("chat2api", None)
    assert "Port 8000" in sidebar._list_widget.currentItem().text()
    view = AppDetailView(apps["ai-grammar"])
    qtbot.addWidget(view)
    old = AppAIConfig(api_base="http://127.0.0.1:8000", model="original")
    new = old.model_copy(update={"api_base": "http://127.0.0.1:8123"})
    view.load_config(snapshot(old))
    view._model_combo.setEditText("draft-only")
    draft = view.get_current_draft()
    changed = []
    view.config_changed.connect(lambda *args: changed.append(args))
    view.adopt_saved_baseline(snapshot(new), preserve_draft=True)
    assert view.get_current_draft() == draft and view._current_config == new
    assert not changed
    view.adopt_saved_baseline(snapshot(new), preserve_draft=False)
    assert view.get_current_draft() == new and not changed


REPAIR = "Not one of the three supported protocols. Pick a valid one, or Auto to remove the key."
COMPATIBILITY = (
    "Installed build failed protocol compatibility checks. Update the service to enable "
    "protocol selection. Auto stays selectable so a saved protocol can be removed."
)
UNKNOWN = "Protocol support could not be verified — validated by ai-manager only."
LABELS = (
    "Auto — omit the key",
    "OpenAI Chat Completions — /v1/chat/completions",
    "OpenAI Responses — /v1/responses",
    "Anthropic Messages — /v1/messages",
)
VALUES = (None, "/v1/chat/completions", "/v1/responses", "/v1/messages")


@pytest.mark.parametrize("stored", [None, "/v1/responses", "invalid"])
@pytest.mark.parametrize("status,accepted", [
    (ProtocolSupportStatus.SUPPORTED, ENDPOINT_VALUES),
    (ProtocolSupportStatus.PARTIAL, frozenset({"/v1/chat/completions", "/v1/messages"})),
    (ProtocolSupportStatus.UNSUPPORTED, frozenset()),
    (ProtocolSupportStatus.UNVERIFIABLE, frozenset()),
])
def test_all_availability_cells(qtbot, tmp_path, stored, status, accepted):
    view = AppDetailView(meta_for(tmp_path))
    qtbot.addWidget(view)
    config = AppAIConfig(endpoint=stored if stored != "invalid" else None,
                         endpoint_raw="'/bad'" if stored == "invalid" else None)
    view.load_config(snapshot(config))
    events = []
    view.config_changed.connect(lambda *args: events.append(args))
    support = ProtocolSupport(status, accepted, "probe <not markup>")
    view.set_protocol_support(support)
    view.set_protocol_support(support)
    enabled = {view._protocol_combo.itemData(i) for i in range(4)
               if view._protocol_combo.model().item(i).isEnabled()}
    want = {None} | (set(ENDPOINT_VALUES) if status in (
        ProtocolSupportStatus.SUPPORTED, ProtocolSupportStatus.UNVERIFIABLE) else set(accepted))
    if stored in ENDPOINT_VALUES:
        want.add(stored)
    assert enabled == want and events == []
    for i in range(4):
        label = view._protocol_combo.itemText(i)
        assert label == LABELS[i] + ("" if VALUES[i] in want else " unavailable")
        assert label.count(" unavailable") == (0 if view._protocol_combo.itemData(i) in want else 1)
    assert (view.get_current_draft().endpoint, view.get_current_draft().endpoint_raw) == (config.endpoint, config.endpoint_raw)
    notice = "" if status is ProtocolSupportStatus.SUPPORTED else (
        UNKNOWN if status is ProtocolSupportStatus.UNVERIFIABLE else COMPATIBILITY
    )
    assert view._capability_notice.text() == notice
    assert view._config_error_details.toPlainText() == (
        "" if status is ProtocolSupportStatus.SUPPORTED else "probe <not markup>"
    )
    assert view._save_only_btn.isEnabled() and view._save_restart_btn.isEnabled()
    assert view._provider_group.isEnabled() and view._model_group.isEnabled()


@pytest.mark.parametrize("raw", ["None", "''", "'/v1/completions'", "42", "True", "'<bad&>'"])
def test_raw_evidence_requires_explicit_activation(qtbot, tmp_path, raw):
    view = AppDetailView(meta_for(tmp_path))
    qtbot.addWidget(view)
    view.load_config(snapshot(AppAIConfig(endpoint_raw=raw)))
    events = []
    view.config_changed.connect(lambda *args: events.append(args))
    combo = view._protocol_combo
    assert combo.currentText() == f"Invalid: {raw}"
    assert combo.count() == 5 and not combo.model().item(4).isEnabled()
    assert view.get_current_draft().endpoint is None
    view._model_combo.setCurrentText("pending")
    view._key_edit.setText("pending-key")
    view._base_url_edit.setText("https://pending")
    assert view.get_current_draft().endpoint_raw == raw
    assert view._protocol_hint.text() == "Unavailable — " + REPAIR
    assert view._request_url_label.text() == "Request URL: unavailable — " + REPAIR
    assert view._save_only_btn.isEnabled()
    auto = combo.findData(None)
    combo.setCurrentIndex(auto)
    combo.activated.emit(auto)
    assert view.get_current_draft().endpoint_raw is None
    assert view._protocol_edited and events
    count = len(events)
    combo.activated.emit(auto)
    assert len(events) == count
    assert combo.count() == 4 and combo.currentData() is None


def test_blocked_protocol_display_requires_same_index_activation_to_repair(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path))
    qtbot.addWidget(view)
    view.load_config(snapshot(AppAIConfig(endpoint_raw="None")))
    events = []
    view.config_changed.connect(lambda *args: events.append(args))
    with QSignalBlocker(view._protocol_combo):
        view._protocol_combo.setCurrentIndex(0)
    assert view.get_current_draft().endpoint_raw == "None" and events == []
    view._protocol_combo.activated.emit(0)
    assert view.get_current_draft().endpoint_raw is None and view._protocol_edited
    assert len(events) == 1


@pytest.mark.parametrize("stored", [None, "/v1/responses"])
def test_support_refresh_keeps_rejected_pending_selection(qtbot, tmp_path, stored):
    view = AppDetailView(meta_for(tmp_path))
    qtbot.addWidget(view)
    view.load_config(snapshot(AppAIConfig(endpoint=stored)))
    view._protocol_combo.setCurrentIndex(3)
    events = []
    view.config_changed.connect(lambda *args: events.append(args))
    view.set_protocol_support(ProtocolSupport(ProtocolSupportStatus.UNSUPPORTED))
    assert view._protocol_combo.currentData() == "/v1/messages"
    assert not view._protocol_combo.model().item(3).isEnabled()
    assert view.get_current_draft().endpoint == "/v1/messages"
    assert view._protocol_edited and events == []
    view._protocol_combo.setCurrentIndex(0 if stored is None else 2)
    assert not view._protocol_edited


@pytest.mark.parametrize("app", ["ai-grammar", "textkit"])
def test_protocol_layout_labels_and_plain_text(qtbot, tmp_path, app):
    view = AppDetailView(meta_for(tmp_path, app))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    combo = view._protocol_combo
    assert not combo.isEditable()
    assert tuple(combo.itemText(i) for i in range(4)) == LABELS
    assert tuple(combo.itemData(i) for i in range(4)) == VALUES
    layout = view._provider_group.layout()
    row = layout.indexOf(combo)
    assert row == 2 and layout.itemAt(0).layout().indexOf(view._preset_combo) >= 0
    assert layout.itemAt(row - 1).widget().text() == "Upstream protocol"
    assert row < layout.indexOf(view._base_url_edit) < layout.indexOf(view._key_edit)
    assert layout.indexOf(view._base_url_edit) + 1 == layout.indexOf(view._request_url_label)
    assert layout.indexOf(view._capability_notice) < layout.indexOf(view._base_url_edit)
    for label in view.findChildren(QLabel):
        assert label.textFormat() == Qt.TextFormat.PlainText
    assert view._capability_notice.text() == UNKNOWN
    assert view._reload_btn.text() == "Reload configuration" and view._reload_btn.isHidden()
    reloads = []
    view.reload_requested.connect(reloads.append)
    view.set_recovery_state(load_failed=True, message="load <failed>", detail="<details>")
    view._reload_btn.click()
    assert reloads == [app]


@pytest.mark.parametrize("app,base,want", [
    ("ai-grammar", "https://x", "https://x/v1/chat/completions"),
    ("ai-grammar", "https://x/v1", "https://x/v1/chat/completions"),
    ("ai-grammar", "https://x/v1/", "https://x/v1//chat/completions"),
    ("textkit", "https://x", "https://x/v1/chat/completions"),
    ("textkit", "https://x/v1", "https://x/v1/v1/chat/completions"),
    ("textkit", "https://x/v1/", "https://x/v1/v1/chat/completions"),
])
def test_protocol_legacy_url_and_hint(qtbot, tmp_path, app, base, want):
    view = AppDetailView(meta_for(tmp_path, app))
    qtbot.addWidget(view)
    view.load_config(snapshot(AppAIConfig(api_base=base)))
    assert view._protocol_hint.text() == "legacy Chat Completions - Authorization: Bearer"
    assert view._request_url_label.text() == "Request URL: " + want


@pytest.mark.parametrize("app", ["ai-grammar", "textkit"])
@pytest.mark.parametrize("endpoint,hint", [
    ("/v1/chat/completions", "Sends Authorization: Bearer"),
    ("/v1/responses", "Sends Authorization: Bearer"),
    ("/v1/messages", "Sends x-api-key + anthropic-version: 2023-06-01"),
])
@pytest.mark.parametrize("base", ["https://x", "https://x/", "https://x/gateway/", "https://x/v1", "https://x/v1/", "https://[", "https://[::1"])
def test_protocol_explicit_url_and_hint(qtbot, tmp_path, app, endpoint, hint, base):
    view = AppDetailView(meta_for(tmp_path, app))
    qtbot.addWidget(view)
    view.load_config(snapshot(AppAIConfig(api_base=base, endpoint=endpoint)))
    assert view._protocol_hint.text() == hint
    assert view._request_url_label.text() == "Request URL: " + base.rstrip("/") + endpoint
    assert ("#ef4444" in view._base_url_edit.styleSheet()) == (base in ("https://x/v1", "https://x/v1/"))
    assert ("#ef4444" in view._request_url_label.styleSheet()) == (base in ("https://x/v1", "https://x/v1/"))
    assert view._save_only_btn.isEnabled() and view._save_restart_btn.isEnabled()
    view._protocol_combo.setCurrentIndex(0)
    assert "#ef4444" not in view._base_url_edit.styleSheet()


@pytest.mark.parametrize("app", ["ai-grammar", "textkit"])
@pytest.mark.parametrize("endpoint", VALUES)
@pytest.mark.parametrize("present", [False, True])
def test_request_url_uses_snapshot_base_presence_and_reversion(qtbot, tmp_path, app, endpoint, present):
    view = AppDetailView(meta_for(tmp_path, app))
    qtbot.addWidget(view)
    view.load_config(snapshot(AppAIConfig(endpoint=endpoint), present=present))
    suffix = endpoint or "/v1/chat/completions"
    initial = ("http://127.0.0.1:3000" if present else "https://api.openai.com") + suffix
    assert view._request_url_label.text() == "Request URL: " + initial
    view._base_url_edit.setText("https://pending/gateway/")
    assert view._request_url_label.text() == "Request URL: https://pending/gateway" + suffix
    view._base_url_edit.setText("http://127.0.0.1:3000")
    assert view._request_url_label.text() == "Request URL: " + initial


def test_unmanaged_app_has_no_protocol_widgets_or_hidden_split_path(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path, "yt2txt", selectable=False))
    qtbot.addWidget(view)
    view.load_config(snapshot(AppAIConfig(is_split_model=True, ocr_model="hidden", endpoint="/v1/messages", endpoint_raw="bad")))
    assert view._protocol_combo is None
    assert all(getattr(view, name, None) is None for name in (
        "_protocol_hint", "_request_url_label", "_capability_notice"
    ))
    assert "Upstream protocol" not in [label.text() for label in view.findChildren(QLabel)]
    view._split_chk.setChecked(True)
    draft = view.get_current_draft()
    assert (draft.endpoint, draft.endpoint_raw, draft.is_split_model, draft.ocr_model) == (None, None, False, None)


def test_capability_refresh_preserves_recovery_and_detail_priority(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path))
    qtbot.addWidget(view)
    view.load_config(snapshot())
    view.set_recovery_state(load_failed=True, conflicts=("api_base",), message="recovery <error>", detail="recovery <detail>")
    view.show_config_error("ordinary <error>", "ordinary <detail>")
    view.set_protocol_support(ProtocolSupport(ProtocolSupportStatus.UNVERIFIABLE, detail="probe <detail>"))
    assert view._config_error_label.text() == "recovery <error>"
    assert view._config_error_details.toPlainText() == "recovery <detail>"
    assert not view._reload_btn.isHidden()
    assert not view._save_only_btn.isEnabled() and not view._save_restart_btn.isEnabled()
    assert view._provider_group.isEnabled() and view._model_group.isEnabled()
    view.set_save_in_progress(True)
    view.set_save_in_progress(False)
    assert not view._save_only_btn.isEnabled()
    view.set_recovery_state(load_failed=False)
    assert view._config_error_label.text() == "ordinary <error>"
    assert view._config_error_details.toPlainText() == "ordinary <detail>"
    view.show_config_error("Configuration saved.")
    assert view._config_error_details.toPlainText() == "probe <detail>"
    assert view._save_only_btn.isEnabled() and view._reload_btn.isHidden()
    view.set_recovery_state(load_failed=False, conflicts=("endpoint",))
    assert not view._save_restart_btn.isEnabled() and not view._reload_btn.isHidden()
    view.set_protocol_support(ProtocolSupport(ProtocolSupportStatus.SUPPORTED, ENDPOINT_VALUES))
    assert not view._save_restart_btn.isEnabled()
    view.set_recovery_state(load_failed=False)
    assert view._config_error_details.isHidden()


def test_display_draft_keeps_snapshot_and_recovery_without_signals(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path))
    qtbot.addWidget(view)
    view.load_config(snapshot(AppAIConfig(model="saved", endpoint_raw="None"), present=False))
    owned = view._snapshot
    baseline = view._current_config
    view.set_protocol_support(ProtocolSupport(ProtocolSupportStatus.UNSUPPORTED, detail="probe <detail>"))
    view.set_recovery_state(load_failed=True, message="recovery", detail="recovery detail")
    events = []
    view.config_changed.connect(lambda *args: events.append(args))
    pending = AppAIConfig(api_base="https://pending", model="pending", endpoint="/v1/messages")
    view._display_draft(pending)
    assert view._snapshot is owned and view._current_config is baseline
    assert (view._loaded_endpoint, view._loaded_endpoint_raw) == (None, "None")
    assert view.get_current_draft() == pending and view._protocol_edited
    assert view._config_error_label.text() == "recovery"
    assert view._config_error_details.toPlainText() == "recovery detail"
    assert view._capability_notice.text() == COMPATIBILITY
    assert not view._save_only_btn.isEnabled() and events == []


def test_snapshot_load_and_adoption_are_owned_silent_and_reset_intent(qtbot, tmp_path):
    view = AppDetailView(meta_for(tmp_path))
    qtbot.addWidget(view)
    initial = snapshot(AppAIConfig(model="saved", endpoint="/v1/messages"))
    events = []
    view.config_changed.connect(lambda *args: events.append(args))
    view.load_config(initial)
    initial.config.model = "caller mutation"
    assert view._snapshot.config.model == "saved" and view._current_config.model == "saved"
    view._protocol_combo.setCurrentIndex(0)
    view._model_combo.setCurrentText("pending")
    pending = view.get_current_draft()
    events.clear()
    committed = snapshot(AppAIConfig(model="committed", endpoint="/v1/responses"), present=False, digest=b"c" * 32)
    assert view.adopt_saved_baseline(committed, preserve_draft=True) == ()
    assert view.get_current_draft() == pending and events == []
    assert view._snapshot.sha256 == b"c" * 32 and not view._snapshot.api_base_present
    assert (view._loaded_endpoint, view._loaded_endpoint_raw) == ("/v1/responses", None)
    assert view._protocol_edited
    assert view.adopt_saved_baseline(committed, preserve_draft=False) == ()
    assert view.get_current_draft() == committed.config and not view._protocol_edited and events == []
    assert not view._is_loading


def test_display_failure_releases_guards_and_retains_view_baseline(qtbot, tmp_path, monkeypatch):
    view = AppDetailView(meta_for(tmp_path))
    qtbot.addWidget(view)
    view.load_config(snapshot(AppAIConfig(model="saved")))
    old = view._snapshot
    with monkeypatch.context() as patch:
        patch.setattr(view._key_edit, "setText", lambda text: (_ for _ in ()).throw(RuntimeError("display fixture")))
        with pytest.raises(RuntimeError, match="display fixture"):
            view.load_config(snapshot(AppAIConfig(api_base="https://new", model="new")))
    assert not view._is_loading
    assert view._snapshot is old and view._current_config.model == "saved"
    events = []
    view.config_changed.connect(lambda *args: events.append(args))
    view._base_url_edit.setText("https://after-failure")
    assert events and not view._base_url_edit.signalsBlocked()
    assert not view._protocol_combo.signalsBlocked() and not view._model_combo.signalsBlocked()


def test_model_refresh_preserves_blank_and_pending_models_without_dirty_event(qtbot):
    view = AppDetailView(get_managed_apps(Path("/tmp"))["textkit"])
    qtbot.addWidget(view)
    events = []
    view.config_changed.connect(lambda *args: events.append(args))
    view.set_available_models(["first", "second"])
    assert view.get_current_draft().model is None and events == []
    view.load_config(snapshot())
    view.set_available_models(["first", "second"])
    assert view.get_current_draft().model is None and events == []
    view._model_combo.setCurrentText("pending")
    events.clear()
    view.set_available_models(["other"])
    assert view.get_current_draft().model == "pending" and events == []
    view.load_config(snapshot(AppAIConfig(is_split_model=True)))
    view.set_available_models(["discovered"])
    draft = view.get_current_draft()
    assert (draft.ocr_model, draft.text_model) == (None, None) and events == []
