"""Integration tests for the five-view MainWindow coordinator.

Workers are completed synchronously by the test so every assertion observes a
deterministic GUI-thread state instead of racing a QThreadPool.
"""

import copy
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
    assert window._draft_configs["ai-grammar"] == retained
    assert grammar.get_current_draft() == retained
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
    window._reload_config("chat2api")
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
