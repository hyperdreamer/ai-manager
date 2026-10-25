"""Integration tests for the five-view MainWindow coordinator.

Workers are completed synchronously by the test so every assertion observes a
deterministic GUI-thread state instead of racing a QThreadPool.
"""

import copy
import gc
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QDialog

from ai_manager.config.config_errors import (
    ConfigError,
    ConfigValidationError,
    ServiceValidationError,
    ServiceValidationTimeout,
    StaleDocumentError,
    TransactionError,
    UnknownConfigKindError,
)
from ai_manager.config.models import (
    AppAIConfig,
    ModelFetchRequest,
    ModelFetchResponse,
    ServiceRunState,
    ServiceStatus,
)
from ai_manager.config.structured_config import load, render
from ai_manager.config.structured_models import (
    FieldIssue,
    LauncherProbeResult,
    Mutation,
    SaveResult,
    TransactionReport,
    ValidationResult,
)
from ai_manager.ui import main_window as mw
from ai_manager.ui.app_detail_view import AppDetailView
from ai_manager.ui.structured_config_view import StructuredConfigView


@pytest.fixture
def window(qtbot, five_app_workspace, monkeypatch):
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a: None)
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a: None)
    monkeypatch.setattr(mw.QMessageBox, "critical", lambda *a: None)
    # closeEvent asks ``QMessageBox.question`` when a draft is dirty. pytest-qt's
    # teardown closes every registered widget, so an unanswered modal would block
    # the suite forever. Tests that intentionally leave dirty state hit this path.
    monkeypatch.setattr(
        mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.StandardButton.Discard
    )
    monkeypatch.setattr(
        mw.BlastRadiusDialog, "exec", lambda self: QDialog.DialogCode.Accepted
    )
    monkeypatch.setattr(mw.BlastRadiusDialog, "selected_app_ids", lambda self: ())
    result = mw.MainWindow(workspace_root=five_app_workspace)
    qtbot.addWidget(result)
    result.thread_pool = MagicMock()
    result.supervisor_manager.restart_service = MagicMock()
    return result


def port_draft(window, port=8123):
    doc = window._saved_configs["chat2api"]
    return replace(doc, mutations=(Mutation(("server", "port"), "set", port),))


def run_save(qtbot, window, monkeypatch, app_id="chat2api", draft=None, restart=False):
    import ai_manager.services.service_validation as validation

    monkeypatch.setattr(
        validation,
        "validate_candidate",
        lambda *a: ValidationResult(
            "manager-only", "validated by ai-manager only — service validator unavailable"
        ),
    )
    draft = draft or window._draft_configs[app_id]
    window._on_config_changed(app_id, draft)
    window._on_save_requested(app_id, draft, restart)
    job = window._save_jobs[app_id]
    job.run()
    qtbot.waitUntil(lambda: app_id not in window._save_jobs)


def test_five_views_saved_ports_dirty_revert_and_kind_refusal(window):
    assert len(window.views) == 5 and not window.has_unsaved_changes()
    assert all(
        isinstance(window.views[a], AppDetailView)
        for a in ("ai-grammar", "textkit", "yt2txt")
    )
    assert all(
        isinstance(window.views[a], StructuredConfigView)
        for a in ("chat2api", "file-bridge")
    )
    window._on_config_changed("chat2api", port_draft(window))
    assert window._is_dirty("chat2api") and window.has_unsaved_changes()
    assert window.sidebar._configured_ports["chat2api"] == 8000
    assert "Port 8000" in window.views["chat2api"]._title_label.text()
    window._on_config_changed(
        "chat2api", replace(window._saved_configs["chat2api"], mutations=())
    )
    assert not window.has_unsaved_changes()
    window._on_save_requested("chat2api", AppAIConfig(), False)
    assert not window._save_jobs
    assert (
        window.views["chat2api"]._notice_label.text()
        == "Configuration draft does not match this app's config kind; save refused."
    )
    with pytest.raises(ValueError):
        window.sidebar.update_configured_port("chat2api", True)
    with pytest.raises(ValueError):
        window.sidebar.update_configured_port("chat2api", 65536)
    with pytest.raises(KeyError):
        window.sidebar.update_configured_port("unknown", None)


def test_unsupported_config_kind_refuses_dispatch_instead_of_silent_fallback(
    qapp, five_app_workspace, monkeypatch
):
    """An unregistered ``config_kind`` must abort construction, never fall back.

    The five registered ids are covered by the dispatch test above, but that test
    cannot see a regression that replaces the unknown-kind ``raise`` with a
    silent ``AppDetailView`` fallback. Inject a sixth app whose kind is not
    registered and require ``MainWindow`` itself to refuse it.

    ``AppMetadata.config_kind`` has a ``mode="before"`` field validator that
    rejects any kind outside llm/chat2api/file-bridge, so pydantic would raise
    before ``MainWindow`` ever saw the value. The metadata is therefore built
    from a real record with a valid kind and the unsupported value is injected
    with ``object.__setattr__``, which is exactly the "metadata validation was
    bypassed" situation the guard must still cover.
    """
    registered = mw.get_managed_apps(five_app_workspace)
    unsupported = registered["chat2api"].model_copy()
    object.__setattr__(unsupported, "id", "quantum-app")
    object.__setattr__(unsupported, "config_kind", "quantum")
    assert unsupported.config_kind == "quantum"  # validator really was bypassed
    apps = dict(registered)
    apps["quantum-app"] = unsupported
    monkeypatch.setattr(mw, "get_managed_apps", lambda root: apps)

    created: list[tuple[str, str]] = []

    def recording(factory, label):
        class Recorder(factory):
            def __init__(self, app_meta, parent=None):
                created.append((app_meta.id, label))
                super().__init__(app_meta, parent)

        return Recorder

    monkeypatch.setattr(mw, "AppDetailView", recording(mw.AppDetailView, "AppDetailView"))
    monkeypatch.setattr(
        mw, "StructuredConfigView", recording(mw.StructuredConfigView, "StructuredConfigView")
    )

    with pytest.raises(UnknownConfigKindError) as excinfo:
        mw.MainWindow(workspace_root=five_app_workspace)
    # Every registered app got its adapter; the unsupported one got none. A
    # fallback would add a sixth record (and, for StructuredConfigView, raise
    # from the wrong site), so this pins the branch rather than just the class.
    assert created == [
        (
            app_id,
            "AppDetailView"
            if registered[app_id].config_kind == "llm"
            else "StructuredConfigView",
        )
        for app_id in registered
    ]
    # The captured traceback keeps the ``__init__`` frame (and with it the
    # half-built window) alive. Drop it and collect the window/tray cycle so no
    # orphan top-level widget outlives this test.
    assert excinfo.value.kind == "quantum"
    error = excinfo.value
    del excinfo, error
    gc.collect()


@pytest.mark.parametrize("gate", [None, LauncherProbeResult(False, "old launcher")])
def test_gate_refuses_forged_listener_draft_but_allows_auth_save(window, gate):
    window._launcher_gate_cache[window.apps["chat2api"].relative_path.resolve()] = gate
    window.views["chat2api"].set_launcher_gate(gate)
    window._on_save_requested("chat2api", port_draft(window), True)
    assert not window._save_jobs and not window._pending_restarts
    assert (
        window.views["chat2api"]._notice_label.text()
        == "Launcher has not passed the configuration probe; host/port changes cannot be saved."
    )
    auth = replace(
        window._saved_configs["chat2api"],
        mutations=(Mutation(("server", "auth_token_env"), "set", "OTHER_TOKEN"),),
    )
    window._on_save_requested("chat2api", auth, False)
    assert "chat2api" in window._save_jobs
    assert not window.views["chat2api"]._save_only_btn.isEnabled()
    assert window.views["chat2api"]._restart_btn.isEnabled()
    first = window._save_jobs["chat2api"]
    window._on_save_requested("chat2api", auth, True)
    assert (
        window._save_jobs["chat2api"] is first
        and window._pending_restarts["chat2api"] is False
    )
    window._on_structured_save_failed("chat2api", ConfigError("fixture failure"))


def test_commit_then_restart_failure_keeps_sealed_state(qtbot, window, monkeypatch):
    run_save(qtbot, window, monkeypatch, draft=port_draft(window), restart=True)
    assert not window.has_unsaved_changes()
    assert window.sidebar._configured_ports["chat2api"] == 8123
    assert window._saved_configs["chat2api"].doc["server"]["port"] == 8123
    assert not window._pending_restarts
    assert (
        window.views["chat2api"]._validation_label.text()
        == "validated by ai-manager only — service validator unavailable"
    )
    window.supervisor_manager.restart_service.assert_called_once_with("chat2api")
    path = window._saved_configs["chat2api"].path
    sealed = path.read_bytes()
    window._on_supervisor_action("restart chat2api", False, "port busy")
    assert (
        window.views["chat2api"]._notice_label.text()
        == "Configuration saved, but service restart failed: port busy"
    )
    assert path.read_bytes() == sealed and not window._is_dirty("chat2api")


@pytest.mark.parametrize(
    "error",
    [
        ConfigValidationError(
            (FieldIssue(("server", "port"), "Port must be an integer from 1 to 65535."),)
        ),
        ServiceValidationError(3, "fixture stdout\n", "<exact & stderr>\n"),
        ServiceValidationTimeout("fixture stdout\n", "timeout stderr\n"),
        TransactionError(
            TransactionReport(
                phase="stage",
                files={Path("/tmp/fixture-config"): "restored"},
                error="injected stage failure",
            )
        ),
    ],
)
def test_save_failure_retains_dirty_draft_and_never_restarts(window, monkeypatch, error):
    monkeypatch.setattr(
        mw.TransactionReportDialog, "exec", lambda self: QDialog.DialogCode.Accepted
    )
    draft = port_draft(window)
    window._on_config_changed("chat2api", draft)
    before = window._saved_configs["chat2api"].raw_bytes
    window._on_save_requested("chat2api", draft, True)
    window._on_structured_save_failed("chat2api", error)
    assert window._draft_configs["chat2api"] == draft and window._is_dirty("chat2api")
    assert window._saved_configs["chat2api"].path.read_bytes() == before
    assert not window._pending_restarts and not window._save_jobs
    assert window.views["chat2api"]._save_only_btn.isEnabled()
    if isinstance(error, (ServiceValidationError, ServiceValidationTimeout)):
        assert window.views["chat2api"]._details.toPlainText() == error.stderr
    window.supervisor_manager.restart_service.assert_not_called()


def test_selected_dependents_reconcile_current_dirty_widgets(qtbot, window, monkeypatch):
    monkeypatch.setattr(
        mw.BlastRadiusDialog,
        "selected_app_ids",
        lambda self: ("textkit", "ai-grammar"),
    )
    original_yt = window._saved_configs["yt2txt"].model_copy(deep=True)
    draft = port_draft(window)
    window._on_config_changed("chat2api", draft)
    window._on_save_requested("chat2api", draft, False)
    # Edit after worker creation: reconciliation must inspect the current draft.
    grammar = window.views["ai-grammar"]
    grammar._model_combo.setEditText("unsaved-user-model")
    retained = window._draft_configs["ai-grammar"].model_copy(deep=True)
    import ai_manager.services.service_validation as validation

    monkeypatch.setattr(
        validation, "validate_candidate", lambda *a: ValidationResult("service", "fixture valid")
    )
    window._save_jobs["chat2api"].run()
    qtbot.waitUntil(lambda: not window._save_jobs)
    assert window._saved_configs["textkit"].api_base == "http://127.0.0.1:8123"
    assert (
        window._draft_configs["textkit"] == window._saved_configs["textkit"]
        and not window._is_dirty("textkit")
    )
    assert window._saved_configs["ai-grammar"].api_base == "http://127.0.0.1:8123"
    # The user's unsaved model edit survives; the field they did not touch (api_base)
    # is adopted from the committed rewrite, and the coordinator draft matches the
    # widgets rather than the pre-rebase copy.
    assert window._draft_configs["ai-grammar"].model == retained.model
    assert window._draft_configs["ai-grammar"].api_base == "http://127.0.0.1:8123"
    assert grammar.get_current_draft() == window._draft_configs["ai-grammar"]
    assert grammar._current_config == window._saved_configs["ai-grammar"]
    assert window._is_dirty("ai-grammar")
    assert window._saved_configs["yt2txt"] == original_yt
    assert not window._is_dirty("chat2api")
    window.supervisor_manager.restart_service.assert_not_called()


@pytest.mark.parametrize("choice", ["cancel", "diff", "reload"])
def test_stale_actions_do_not_force_overwrite(window, monkeypatch, choice):
    viewed = []
    monkeypatch.setattr(mw.StaleDocumentDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(mw.StaleDocumentDialog, "choice", lambda self: choice)
    monkeypatch.setattr(
        mw.ReviewChangesDialog,
        "exec",
        lambda self: viewed.append(True) or QDialog.DialogCode.Accepted,
    )
    draft = port_draft(window)
    window._on_config_changed("chat2api", draft)
    window._on_save_requested("chat2api", draft, False)
    path = draft.path
    changed = json.loads(path.read_bytes())
    changed["server"]["port"] = 8222
    path.write_text(json.dumps(changed))
    raw = path.read_bytes()
    window._on_structured_save_failed(
        "chat2api", StaleDocumentError(path, draft.raw_sha256, hashlib.sha256(raw).digest())
    )
    assert path.read_bytes() == raw and not window._save_jobs
    assert bool(viewed) is (choice == "diff")
    if choice == "reload":
        assert window._saved_configs["chat2api"].doc["server"]["port"] == 8222
        assert not window._is_dirty("chat2api")
    else:
        assert window._draft_configs["chat2api"] == draft and window._is_dirty("chat2api")


def test_missing_explicit_create_invalid_raw_and_failed_reload_protect_draft(window, monkeypatch):
    path = window.apps["chat2api"].relative_path / "config.json"
    path.unlink()
    llm_reader = MagicMock(side_effect=AssertionError("structured reload used LLM reader"))
    monkeypatch.setattr(mw, "read_app_config_snapshot", llm_reader)
    window._reload_config("chat2api")
    llm_reader.assert_not_called()
    view = window.views["chat2api"]
    assert not window.has_unsaved_changes() and not view._save_only_btn.isEnabled()
    assert "chat2api" not in window.sidebar._configured_ports
    view._create_from_example()
    assert not path.exists() and window._is_dirty("chat2api")
    row = view._model.rows[0].id
    view._on_raw_options_changed(row, "{broken")
    retained = copy.deepcopy(window._draft_configs["chat2api"])
    path.write_text("[]")
    window._reload_config("chat2api")
    assert window._draft_configs["chat2api"] == retained and window.has_unsaved_changes()
    assert not view._save_only_btn.isEnabled()
    assert view._model.row(row).raw_text == "{broken"


def test_fetch_origin_survives_equal_tokens_navigation_and_non_llm_origin(window, monkeypatch):
    workers = []

    class ControlledWorker:
        def __init__(self, request):
            self.request = request
            from ai_manager.services.model_fetcher import ModelFetchSignals

            self.signals = ModelFetchSignals()
            workers.append(self)

    monkeypatch.setattr(mw, "ModelFetchWorker", ControlledWorker)
    for app_id in ("ai-grammar", "textkit"):
        window.views[app_id].on_model_fetch_response = MagicMock()
        window._on_fetch_models(
            ModelFetchRequest(
                token=1, api_base="http://fixture", api_key="", app_id=app_id
            )
        )
    window.sidebar.select_app("file-bridge")
    response = ModelFetchResponse(token=1, success=True, models=["fixture-model"])
    window._on_models_fetched("ai-grammar", response)
    window.views["ai-grammar"].on_model_fetch_response.assert_called_once_with(response)
    window.views["textkit"].on_model_fetch_response.assert_not_called()
    with pytest.raises(ConfigError):
        window._on_fetch_models(
            ModelFetchRequest(
                token=1, api_base="http://fixture", api_key="", app_id="missing"
            )
        )
    with pytest.raises(ConfigError):
        window._on_fetch_models(
            ModelFetchRequest(
                token=1, api_base="http://fixture", api_key="", app_id="file-bridge"
            )
        )
    window._on_models_fetched("file-bridge", response)
    window._on_models_fetched("removed", response)


def test_probe_once_per_resolved_directory_and_completion_keeps_other_controls(window, monkeypatch):
    # Call the production method explicitly because the autouse fixture substitutes startup.
    path = window.apps["chat2api"].relative_path.resolve()
    window._launcher_gate_cache.clear()
    window._probe_jobs.clear()
    # Task 1's isolate_manager stores the production function before replacing it:
    # see fixture amendment in Step 2 of the task brief.
    window._production_start_launcher_probes()
    window._production_start_launcher_probes()
    assert len(window._probe_jobs) == 1
    assert window.views["chat2api"]._fields[("server", "port")].isEnabled() is False
    window._on_launcher_probe_finished(
        "chat2api",
        LauncherProbeResult(False, "fixture failure", stderr="exact probe error\n"),
    )
    assert path in window._launcher_gate_cache and not window._probe_jobs
    assert window.views["chat2api"]._fields[("server", "auth_token_env")].isEnabled()
    assert (
        window.views["chat2api"]._details.toPlainText()
        == "fixture failure\nexact probe error\n"
    )
    window._production_start_launcher_probes()
    assert not window._probe_jobs


def test_actual_worker_completion_is_queued_and_gui_remains_responsive(
    qtbot, window, monkeypatch
):
    from threading import Event

    from PyQt6.QtCore import QThread, QThreadPool, QTimer

    from ai_manager.config import structured_config as sc

    entered, release = Event(), Event()
    observed = []

    def blocked_commit(*args, **kwargs):
        observed.append(("worker", QThread.currentThread()))
        entered.set()
        assert release.wait(5), "test did not release worker"
        raise ServiceValidationError(3, "", "queued stderr\n")

    monkeypatch.setattr(sc, "commit", blocked_commit)
    view = window.views["chat2api"]
    original = view.show_config_error

    def checked_message(message, detail=None):
        observed.append(("gui", QThread.currentThread()))
        assert QThread.currentThread() is window.thread()
        return original(message, detail)

    monkeypatch.setattr(view, "show_config_error", checked_message)
    pool = QThreadPool(window)
    window.thread_pool = pool
    window._on_config_changed("chat2api", port_draft(window))
    try:
        window._on_save_requested("chat2api", port_draft(window), True)
        qtbot.waitUntil(entered.is_set)
        ticks = []
        QTimer.singleShot(0, lambda: (view._tabs.setCurrentIndex(1), ticks.append(True)))
        qtbot.waitUntil(lambda: bool(ticks))
        assert "chat2api" in window._save_jobs and not view._save_only_btn.isEnabled()
        release.set()
        qtbot.waitUntil(lambda: not window._save_jobs)
        assert any(
            role == "worker" and thread is not window.thread()
            for role, thread in observed
        )
        assert any(role == "gui" for role, thread in observed)
        assert view._details.toPlainText() == "queued stderr\n"
        window.supervisor_manager.restart_service.assert_not_called()
    finally:
        release.set()
        assert pool.waitForDone(5000)


def test_fetch_reverse_delivery_equal_tokens_and_late_token(qtbot, window, monkeypatch):
    from ai_manager.services.model_fetcher import ModelFetchSignals

    workers = []

    class ControlledWorker:
        def __init__(self, request):
            self.request, self.signals = request, ModelFetchSignals()
            workers.append(self)

    monkeypatch.setattr(mw, "ModelFetchWorker", ControlledWorker)
    grammar, textkit = window.views["ai-grammar"], window.views["textkit"]
    grammar._on_fetch_clicked()
    textkit._on_fetch_clicked()
    window.sidebar.select_app("chat2api")
    assert workers[0].request.app_id == "ai-grammar"
    assert workers[1].request.app_id == "textkit"
    assert workers[0].request.token == workers[1].request.token == 1
    workers[1].signals.finished.emit(
        ModelFetchResponse(token=1, success=True, models=["textkit-only"])
    )
    workers[0].signals.finished.emit(
        ModelFetchResponse(token=1, success=True, models=["grammar-only"])
    )
    qtbot.waitUntil(lambda: not window._model_workers)
    assert "grammar-only" in grammar._available_models
    assert "grammar-only" not in textkit._available_models
    assert "textkit-only" in textkit._available_models
    assert "textkit-only" not in grammar._available_models
    grammar._on_fetch_clicked()
    window._on_models_fetched(
        "ai-grammar", ModelFetchResponse(token=1, success=True, models=["stale-model"])
    )
    assert "stale-model" not in grammar._available_models
    workers[-1].signals.finished.emit(
        ModelFetchResponse(token=2, success=True, models=["fresh-model"])
    )
    qtbot.waitUntil(lambda: not window._model_workers)
    assert "fresh-model" in grammar._available_models


@pytest.mark.parametrize(
    "app_id,key,value",
    [("chat2api", ("server", "port"), 8123), ("file-bridge", ("port",), 8970)],
)
def test_port_cache_survives_status_dirty_redraw_and_unreadable_reload(
    qtbot, window, monkeypatch, app_id, key, value
):
    saved = window._saved_configs[app_id]
    run_save(
        qtbot,
        window,
        monkeypatch,
        app_id=app_id,
        draft=replace(saved, mutations=(Mutation(key, "set", value),)),
    )
    window.sidebar.select_app(app_id)
    window.sidebar.set_dirty(app_id, True)
    window.sidebar.update_status(
        app_id, ServiceStatus(service_id=app_id, state=ServiceRunState.RUNNING, pid=1)
    )
    assert f"Port {value}" in window.sidebar._list_widget.currentItem().text()
    assert f"Port {value}" in window.views[app_id]._title_label.text()
    assert window.apps[app_id].default_port == (
        8000 if app_id == "chat2api" else 8964
    )
    window._saved_configs[app_id].path.write_bytes(b"[]\n")
    window._reload_config(app_id)
    assert app_id not in window.sidebar._configured_ports
    assert (
        f"Port {window.apps[app_id].default_port}"
        in window.sidebar._list_widget.currentItem().text()
    )


def test_auth_warning_uses_current_dependent_draft_without_key_write(window):
    draft = replace(
        window._saved_configs["chat2api"],
        mutations=(Mutation(("server", "auth_token_env"), "set", "CHAT2API_TOKEN"),),
    )
    window._on_config_changed("chat2api", draft)
    dependent = window._draft_configs["ai-grammar"].model_copy(
        update={"api_key": "$OTHER_TOKEN"}
    )
    window._on_config_changed("ai-grammar", dependent)
    expected = (
        "ai-grammar uses $OTHER_TOKEN, but chat2api auth_token_env is "
        "'CHAT2API_TOKEN'; requests may fail with HTTP 401."
    )
    assert expected in window.views["chat2api"]._auth_label.text()
    assert (
        b'api_key: "$CHAT2API_TOKEN"'
        in (window.apps["ai-grammar"].relative_path / "config.yaml").read_bytes()
    )
    disabled = replace(
        draft, mutations=(Mutation(("server", "auth_token_env"), "set", None),)
    )
    window._on_config_changed("chat2api", disabled)
    assert not window.views["chat2api"]._auth_label.text()


def test_blast_cancel_prevents_worker_and_target_changes(window, monkeypatch):
    monkeypatch.setattr(
        mw.BlastRadiusDialog, "exec", lambda self: QDialog.DialogCode.Rejected
    )
    draft = port_draft(window)
    window._on_config_changed("chat2api", draft)
    original = draft.path.read_bytes()
    window._on_save_requested("chat2api", draft, True)
    assert not window._save_jobs and not window._pending_restarts
    assert draft.path.read_bytes() == original and window._is_dirty("chat2api")
    window.supervisor_manager.restart_service.assert_not_called()


def test_saved_notice_preserves_validator_details_until_next_load(
    qtbot, window, monkeypatch
):
    """``Configuration saved.`` must not erase the validation evidence.

    ``set_validation_result`` installs the notice and details after a commit.
    The plain success notice that follows passes no detail, so the validator
    output has to survive; only loading a different config clears it.
    """
    import ai_manager.services.service_validation as validation

    monkeypatch.setattr(
        validation,
        "validate_candidate",
        lambda *a: ValidationResult(
            "service",
            "Validated by the chat2api service validator.",
            "exact validator stdout\n",
        ),
    )
    draft = port_draft(window)
    window._on_config_changed("chat2api", draft)
    window._on_save_requested("chat2api", draft, False)
    window._save_jobs["chat2api"].run()
    qtbot.waitUntil(lambda: not window._save_jobs)
    view = window.views["chat2api"]
    assert view._notice_label.text() == "Configuration saved."
    assert view._validation_label.text() == "Validated by the chat2api service validator."
    assert view._details.toPlainText() == "exact validator stdout\n"
    # Loading a different configuration starts a fresh validation cycle.
    window._reload_config("chat2api")
    assert view._details.toPlainText() == ""
    assert view._validation_label.text() == "Not validated since load."
