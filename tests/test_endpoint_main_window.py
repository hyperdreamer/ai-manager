"""LLM snapshot ownership, protocol delivery, and the checked save seam."""
import copy
import stat
from dataclasses import FrozenInstanceError
from hashlib import sha256
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QEvent, QProcess, QThread, QThreadPool, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config import transaction as transaction_module, yaml_manager
from ai_manager.config.config_errors import (
    CommittedWriteError,
    ConfigError,
    StaleDocumentError,
    TransactionError,
)
from ai_manager.config.models import AppAIConfig, ConfigSnapshot
from ai_manager.config.structured_models import TransactionReport
from ai_manager.config.transaction import Transaction
from ai_manager.config.protocols import ENDPOINT_VALUES
from ai_manager.services import config_jobs as jobs
from ai_manager.services import protocol_capability as capability
from ai_manager.services.protocol_capability import ProtocolSupport, ProtocolSupportStatus
from ai_manager.config.yaml_manager import read_app_config_snapshot
from ai_manager.ui.app_detail_view import AppDetailView
from ai_manager.ui import main_window as mw


@pytest.fixture(autouse=True)
def finish_prior_widget_deletions(qapp):
    """Complete pytest-qt's deferred teardown before creating another five-app window."""
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def broken_read(root, monkeypatch):
    (root / "ai-grammar/backend/config.yaml").write_bytes(b"ai: [broken\n")


def broken_display(root, monkeypatch):
    original = AppDetailView.load_config

    def display(view, value):
        if view.app_meta.id == "ai-grammar":
            raise RuntimeError("display <fixture>")
        return original(view, value)

    monkeypatch.setattr(AppDetailView, "load_config", display)


def broken_copy(root, monkeypatch):
    original = mw.copy.deepcopy

    def deep(value, *args, **kwargs):
        if isinstance(value, AppAIConfig) and value.model == "original-grammar":
            raise RecursionError("copy <fixture>")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(mw.copy, "deepcopy", deep)


@pytest.mark.parametrize("endpoint_window", [broken_read, broken_display, broken_copy], indirect=True)
def test_initial_load_failure_publishes_no_default_and_keeps_restart_logs(endpoint_window):
    window = endpoint_window
    app_id = "ai-grammar"
    assert app_id not in window._saved_configs
    assert app_id not in window._draft_configs
    assert app_id not in window._snapshots and window._load_failed[app_id]
    assert "textkit" in window._snapshots and "yt2txt" in window._snapshots
    view = window.views[app_id]
    assert view._snapshot is None
    assert not view._provider_group.isEnabled() and not view._model_group.isEnabled()
    assert not view._save_only_btn.isEnabled() and not view._save_restart_btn.isEnabled()
    assert view._tabs.isEnabled() and view.log_view.isEnabled() and view._restart_btn.isEnabled()
    assert not view._reload_btn.isHidden()
    assert view._config_error_label.text().startswith("Cannot load configuration ")
    assert view._config_error_details.toPlainText()
    window._on_config_changed(app_id, AppAIConfig())
    assert app_id not in window._draft_configs and not window._is_dirty(app_id)
    view._restart_btn.click()
    window.supervisor_manager.restart_service.assert_called_once_with(app_id)


def test_initial_snapshots_share_bytes_and_own_separate_saved_and_draft_copies(endpoint_window):
    window = endpoint_window
    assert set(window._snapshots) == {"ai-grammar", "textkit", "yt2txt"}
    for app_id, snapshot in window._snapshots.items():
        meta, view = window.apps[app_id], window.views[app_id]
        assert snapshot.sha256 == sha256((meta.relative_path / meta.config_file_name).read_bytes()).digest()
        assert snapshot.api_base_present is True
        assert not window._load_failed[app_id] and not window._baseline_conflict[app_id]
        assert view._snapshot is not snapshot and view._snapshot == snapshot
        assert window._saved_configs[app_id] == window._draft_configs[app_id] == snapshot.config
        assert window._saved_configs[app_id] is not window._draft_configs[app_id]
        assert window._saved_configs[app_id] is not snapshot.config
        assert window._draft_configs[app_id] is not snapshot.config
        assert view.get_current_draft() == snapshot.config
        assert view._save_only_btn.isEnabled()
    window._draft_configs["ai-grammar"].model = "mutated draft"
    assert window._saved_configs["ai-grammar"].model == "original-grammar"
    assert window._snapshots["ai-grammar"].config.model == "original-grammar"


def test_initial_load_alone_can_copy_example(endpoint_window, monkeypatch):
    window = endpoint_window
    app_id = "ai-grammar"
    meta = window.apps[app_id]
    path = meta.relative_path / meta.config_file_name
    path.unlink()
    # Reproduce the initial ownership branch with this isolated app only.
    window._snapshots.pop(app_id)
    window._saved_configs.pop(app_id)
    window._draft_configs.pop(app_id)
    window._load_failed.pop(app_id)
    window._load_config(app_id)
    assert path.exists() and window._snapshots[app_id].config.model == "original-grammar"


@pytest.mark.parametrize("failure", ["read", "display", "copy"])
def test_load_failure_retains_previous_coordinator_ownership(endpoint_window, monkeypatch, failure):
    window = endpoint_window
    app_id = "ai-grammar"
    view = window.views[app_id]
    view._model_combo.setEditText("pending")
    owned = tuple(store[app_id] for store in (window._snapshots, window._saved_configs, window._draft_configs))
    if failure == "read":
        monkeypatch.setattr(mw, "read_app_config_snapshot", Mock(side_effect=RuntimeError("read <fixture>")))
    elif failure == "display":
        monkeypatch.setattr(view, "load_config", Mock(side_effect=RuntimeError("display <fixture>")))
    else:
        original = mw.copy.deepcopy
        def deep(value, *args, **kwargs):
            if isinstance(value, AppAIConfig):
                raise RecursionError("copy <fixture>")
            return original(value, *args, **kwargs)
        monkeypatch.setattr(mw.copy, "deepcopy", deep)
    window._load_config(app_id)
    assert all(store[app_id] is previous for store, previous in zip(
        (window._snapshots, window._saved_configs, window._draft_configs), owned
    ))
    assert window._load_failed[app_id] and view.get_current_draft().model == "pending"
    assert not view._save_only_btn.isEnabled() and view._provider_group.isEnabled()


@pytest.mark.parametrize("present,edit_base", [(False, False), (False, True), (True, False)])
def test_interim_save_passes_owned_baseline_digest_and_advances_presence(endpoint_window, monkeypatch, present, edit_base):
    window = endpoint_window
    app_id = "ai-grammar"
    meta, view = window.apps[app_id], window.views[app_id]
    path = meta.relative_path / meta.config_file_name
    path.write_text("ai:\n" + ("  api_base: https://saved\n" if present else "") + "  model: old\n")
    window._load_config(app_id)
    old = window._snapshots[app_id]
    view._model_combo.setCurrentText("pending")
    if edit_base:
        view._base_url_edit.setText("https://pending")
    draft = view.get_current_draft()
    actual_writer = mw.write_app_config
    writes = []
    def writer(metadata, candidate, *, baseline, expected_sha256):
        writes.append((metadata, candidate, baseline, expected_sha256))
        return actual_writer(metadata, candidate, baseline=baseline, expected_sha256=expected_sha256)
    monkeypatch.setattr(mw, "write_app_config", writer)
    displays = []
    actual_load = view.load_config
    def load(snapshot):
        displays.append(snapshot)
        return actual_load(snapshot)
    monkeypatch.setattr(view, "load_config", load)
    window._on_save_requested(app_id, draft, False)
    assert len(writes) == 1
    assert writes[0] == (meta, draft, old.config, old.sha256)
    assert writes[0][2] is old.config
    new = window._snapshots[app_id]
    assert displays == [new] and displays[0] is new
    assert new.config == draft and new.sha256 == sha256(path.read_bytes()).digest()
    assert new.api_base_present is (present or edit_base)
    assert window._saved_configs[app_id] == window._draft_configs[app_id] == new.config
    assert not window._is_dirty(app_id) and view._config_error_label.text() == "Configuration saved."
    window.supervisor_manager.restart_service.assert_not_called()


@pytest.mark.parametrize("dirty", [False, True])
def test_interim_dependent_reconciliation_rereads_snapshot(endpoint_window, dirty):
    window = endpoint_window
    app_id = "ai-grammar"
    meta, view = window.apps[app_id], window.views[app_id]
    if dirty:
        view._model_combo.setCurrentText("pending")
    draft = view.get_current_draft()
    path = meta.relative_path / meta.config_file_name
    path.write_text("ai: {api_base: 'https://committed', model: committed, endpoint: /v1/messages}\n")
    incoming = AppAIConfig(api_base="https://untrusted", model="not on disk")
    window._reconcile_dependent_views({app_id: incoming})
    actual = read_app_config_snapshot(meta)
    assert window._snapshots[app_id] == actual
    assert window._saved_configs[app_id] == actual.config
    assert view._current_config == actual.config
    assert window._draft_configs[app_id] == (draft if dirty else actual.config)
    assert view.get_current_draft() == window._draft_configs[app_id]


def test_interim_dependent_read_failure_retains_owned_state(endpoint_window):
    window = endpoint_window
    app_id = "ai-grammar"
    meta, view = window.apps[app_id], window.views[app_id]
    view._model_combo.setCurrentText("pending")
    old = tuple(store[app_id] for store in (window._snapshots, window._saved_configs, window._draft_configs))
    (meta.relative_path / meta.config_file_name).write_bytes(b"[]\n")
    window._reconcile_dependent_views({app_id: AppAIConfig(model="ignored")})
    assert all(store[app_id] is previous for store, previous in zip(
        (window._snapshots, window._saved_configs, window._draft_configs), old
    ))
    assert window._load_failed[app_id] and view.get_current_draft().model == "pending"
    assert not view._save_restart_btn.isEnabled()


class ProtocolPool:
    """Hold real workers until a test chooses their completion order."""

    def __init__(self):
        self.jobs = []

    def start(self, job):
        self.jobs.append(job)


@pytest.fixture
def protocol_pool(endpoint_window):
    pool = ProtocolPool()
    endpoint_window.thread_pool = pool
    return pool


def supported():
    return ProtocolSupport(ProtocolSupportStatus.SUPPORTED, ENDPOINT_VALUES)


def test_protocol_worker_owns_metadata_token_and_generation(qtbot, five_app_workspace, monkeypatch):
    meta = get_managed_apps(five_app_workspace)["ai-grammar"].model_copy(deep=True)
    original = meta.model_copy(deep=True)
    observed = []

    def probe(owned, *, generation, use_cache=True):
        observed.append((owned, generation, use_cache))
        return supported()

    monkeypatch.setattr(jobs, "_probe_protocol_support_at_generation", probe)
    job = jobs.ProtocolProbeJob(meta, token=17, generation=23)
    meta.id = "textkit"
    meta.relative_path = meta.relative_path / "changed"
    meta.supports_protocol_selection = False
    results = []
    job.signals.probe_finished.connect(lambda *args: results.append(args))
    job.run()
    assert results == [("ai-grammar", supported())]
    assert observed == [(original, 23, True)]
    assert observed[0][0] is not meta
    with pytest.raises(AttributeError):
        job.token = 99
    with pytest.raises(AttributeError):
        job.generation = 99
    assert (job.token, job.generation) == (17, 23)


def test_protocol_worker_exception_is_one_redacted_unknown(qtbot, five_app_workspace, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("api_key='worker-secret' input_value='private tail'")

    monkeypatch.setattr(jobs, "_probe_protocol_support_at_generation", broken)
    job = jobs.ProtocolProbeJob(get_managed_apps(five_app_workspace)["ai-grammar"], 1, 0)
    results = []
    job.signals.probe_finished.connect(lambda *args: results.append(args))
    job.run()
    assert len(results) == 1
    app_id, result = results[0]
    assert app_id == "ai-grammar"
    assert result.status is ProtocolSupportStatus.UNVERIFIABLE and not result.accepted
    assert result.detail.startswith("Protocol capability check failed:")
    assert "***" in result.detail
    assert "worker-secret" not in result.detail and "private tail" not in result.detail


def test_queued_protocol_job_keeps_creation_generation_and_never_spawns(qtbot, five_app_workspace, monkeypatch):
    app_id = "ai-grammar"
    generation = capability.protocol_support_generation(app_id)
    job = jobs.ProtocolProbeJob(get_managed_apps(five_app_workspace)[app_id], 1, generation)
    interpreter = five_app_workspace / "probe-interpreter"
    interpreter.write_bytes(b"fixture interpreter")
    resolved, spawned = [], []

    def resolve(path):
        resolved.append(path)
        return interpreter

    def spawn(*args, **kwargs):
        spawned.append(args)
        raise RuntimeError("obsolete job reached spawn")

    monkeypatch.setattr(capability, "resolve_app_interpreter", resolve)
    monkeypatch.setattr(capability.subprocess, "Popen", spawn)
    capability.invalidate_protocol_support(app_id)
    results = []
    job.signals.probe_finished.connect(lambda *args: results.append(args))
    job.run()
    assert spawned == []
    assert resolved == []
    assert len(results) == 1
    assert results[0][1].detail == (
        "Protocol capability check was superseded; retry after the restart or update."
    )
    assert not results[0][1].accepted


def test_probe_completion_is_delivered_in_gui_context(qtbot, endpoint_window, monkeypatch):
    window = endpoint_window
    observed, workers = [], []

    def probe(meta, **kwargs):
        workers.append(QThread.currentThread() != QApplication.instance().thread())
        return supported()

    monkeypatch.setattr(jobs, "_probe_protocol_support_at_generation", probe)
    original = window._on_protocol_probe_finished

    def completion(*args):
        observed.append(QThread.currentThread() == QApplication.instance().thread())
        if observed[-1]:  # A thread-affinity mutant must not update widgets from its worker.
            original(*args)

    monkeypatch.setattr(window, "_on_protocol_probe_finished", completion)
    pool = QThreadPool(window)
    window.thread_pool = pool
    window._start_protocol_probe("ai-grammar")
    try:
        qtbot.waitUntil(lambda: bool(observed), timeout=2000)
        assert observed == [True]
        assert workers == [True]
        assert window._protocol_support["ai-grammar"].accepted == ENDPOINT_VALUES
        assert not window._protocol_probe_jobs and not window._protocol_probe_deliveries
    finally:
        pool.waitForDone(2000)


def test_protocol_startup_runs_after_views_and_keeps_launcher_maps_separate(
    qtbot, five_app_workspace, monkeypatch
):
    pool = ProtocolPool()
    monkeypatch.setattr(QThreadPool, "globalInstance", staticmethod(lambda: pool))
    production = mw.MainWindow._production_start_protocol_probes
    ready = []

    def startup(window):
        ready.append((set(window.views), set(window._snapshots)))
        production(window)

    monkeypatch.setattr(mw.MainWindow, "_start_protocol_probes", startup)
    window = mw.MainWindow(five_app_workspace)
    qtbot.addWidget(window)
    assert ready == [(set(window.apps), {"ai-grammar", "textkit", "yt2txt"})]
    assert [job.meta.id for job in pool.jobs] == ["ai-grammar", "textkit"]
    assert set(window._protocol_probe_jobs) == {("ai-grammar", 1), ("textkit", 1)}
    assert not window._probe_jobs
    assert set(window._launcher_gate_cache) == {window.apps["chat2api"].relative_path.resolve()}
    for key, job in window._protocol_probe_jobs.items():
        assert job is pool.jobs[["ai-grammar", "textkit"].index(key[0])]
        delivery = window._protocol_probe_deliveries[key]
        assert delivery.parent() is window
        assert delivery.thread() == QApplication.instance().thread()
        assert job.generation == capability.protocol_support_generation(key[0])


def test_obsolete_token_retains_newer_job_and_availability(qtbot, endpoint_window, protocol_pool):
    window = endpoint_window
    app_id = "ai-grammar"
    window._start_protocol_probe(app_id)
    window._start_protocol_probe(app_id)
    assert len(protocol_pool.jobs) == 2
    old, new = protocol_pool.jobs
    old_result = ProtocolSupport(ProtocolSupportStatus.UNSUPPORTED, detail="obsolete detail")
    new_result = ProtocolSupport(
        ProtocolSupportStatus.PARTIAL, frozenset({"/v1/messages"}), "current detail"
    )
    before = window._protocol_support[app_id]
    old.signals.probe_finished.emit(app_id, old_result)
    QApplication.processEvents()
    assert (app_id, new.token) in window._protocol_probe_jobs
    assert window._protocol_probe_jobs[(app_id, new.token)] is new
    assert (app_id, old.token) not in window._protocol_probe_jobs
    assert (app_id, new.token) in window._protocol_probe_deliveries
    assert window._protocol_support[app_id] is before
    new.signals.probe_finished.emit(app_id, new_result)
    QApplication.processEvents()
    assert (app_id, new.token) not in window._protocol_probe_jobs
    assert window._protocol_support[app_id] is new_result
    # An already queued callback from the obsolete job cannot replace new detail.
    window._on_protocol_probe_finished(app_id, old.token, old.generation, old_result)
    assert window._protocol_support[app_id] is new_result
    assert window.views[app_id]._config_error_details.toPlainText() == "current detail"
    assert not window._protocol_probe_jobs and not window._protocol_probe_deliveries


def test_reverse_protocol_completions_keep_newest_result(qtbot, endpoint_window, protocol_pool):
    window = endpoint_window
    window._start_protocol_probe("ai-grammar")
    window._start_protocol_probe("ai-grammar")
    assert len(protocol_pool.jobs) == 2
    old, new = protocol_pool.jobs
    new.signals.probe_finished.emit("ai-grammar", supported())
    QApplication.processEvents()
    assert ("ai-grammar", new.token) not in window._protocol_probe_jobs
    assert ("ai-grammar", old.token) in window._protocol_probe_jobs
    old.signals.probe_finished.emit(
        "ai-grammar", ProtocolSupport(ProtocolSupportStatus.UNSUPPORTED, detail="obsolete")
    )
    QApplication.processEvents()
    assert not window._protocol_probe_jobs
    assert window._protocol_support["ai-grammar"] == supported()
    assert window.views["ai-grammar"]._protocol_combo.model().item(3).isEnabled()
    assert window.views["ai-grammar"]._config_error_details.toPlainText() == ""


@pytest.mark.parametrize("stale", ["generation", "removed", "flag"])
def test_protocol_completion_requires_current_generation_and_eligible_app(
    qtbot, endpoint_window, protocol_pool, stale
):
    window = endpoint_window
    app_id = "ai-grammar"
    before = window.views[app_id]._protocol_support
    window._start_protocol_probe(app_id)
    assert len(protocol_pool.jobs) == 1
    job = protocol_pool.jobs[0]
    if stale == "generation":
        capability.invalidate_protocol_support(app_id)
    elif stale == "removed":
        window.apps.pop(app_id)
    else:
        window.apps[app_id].supports_protocol_selection = False
    job.signals.probe_finished.emit(app_id, supported())
    QApplication.processEvents()
    assert not window._protocol_probe_jobs
    assert window.views[app_id]._protocol_support is before
    assert window._protocol_support[app_id] is before
    assert not window._protocol_probe_deliveries


def test_delivery_rejects_wrong_emitted_app_id(qtbot, endpoint_window, protocol_pool):
    window = endpoint_window
    window._start_protocol_probe("ai-grammar")
    assert len(protocol_pool.jobs) == 1
    job = protocol_pool.jobs[0]
    before = dict(window._protocol_support)
    job.signals.probe_finished.emit("textkit", supported())
    QApplication.processEvents()
    assert window._protocol_support == before
    assert ("ai-grammar", job.token) in window._protocol_probe_jobs
    job.signals.probe_finished.emit("ai-grammar", supported())
    qtbot.waitUntil(lambda: not window._protocol_probe_jobs)
    assert window._protocol_support["ai-grammar"] == supported()
    assert window._protocol_support["textkit"] is before["textkit"]


def pending_protocol_draft(window, app_id, raw):
    """Keep every LLM field live, including raw endpoint and split models."""
    view = window.views[app_id]
    path = window.apps[app_id].relative_path / window.apps[app_id].config_file_name
    text = path.read_text()
    path.write_text(text.replace("ai:\n", "ai:\n" + (
        "  endpoint: invalid-fixture\n" if raw else "  endpoint: /v1/messages\n"
    )))
    window._load_config(app_id)
    view._base_url_edit.setText("https://pending.example.test/gateway")
    view._key_edit.setText("pending-key-fixture")
    if app_id == "textkit":
        view._ocr_combo.setEditText("pending-ocr")
        view._text_combo.setEditText("pending-text")
    else:
        view._model_combo.setEditText("pending-model")
    return view.get_current_draft().model_copy(deep=True)


@pytest.mark.parametrize("app_id", ["ai-grammar", "textkit"])
@pytest.mark.parametrize("origin", ["saved", "manual"])
@pytest.mark.parametrize("outcome", ["success", "failure", "busy"])
@pytest.mark.parametrize("raw", [False, True])
def test_every_terminal_restart_reprobes_once_and_preserves_full_draft(
    qtbot, endpoint_window, protocol_pool, monkeypatch, app_id, origin, outcome, raw
):
    window = endpoint_window
    before_draft = pending_protocol_draft(window, app_id, raw)
    before_saved = window._saved_configs[app_id].model_copy(deep=True)
    snapshot = window._snapshots[app_id]
    path = window.apps[app_id].relative_path / window.apps[app_id].config_file_name
    before_bytes = path.read_bytes()
    before_generation = capability.protocol_support_generation(app_id)
    other_id = "textkit" if app_id == "ai-grammar" else "ai-grammar"
    other_generation = capability.protocol_support_generation(other_id)
    invalidations, warnings = [], []
    invalidate = capability.invalidate_protocol_support

    def invalidation(origin_id):
        invalidations.append(origin_id)
        invalidate(origin_id)

    monkeypatch.setattr(mw, "invalidate_protocol_support", invalidation)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    def dispatch(origin_id):
        assert origin_id == app_id
        assert invalidations == [] and protocol_pool.jobs == []
        assert window._submitting_restart == app_id
        if outcome == "busy":
            window.supervisor_manager.action_completed.emit("restart", False, "busy fixture")

    monkeypatch.setattr(window.supervisor_manager, "restart_service", dispatch)
    request = window._request_saved_restart if origin == "saved" else window._on_restart_requested
    request(app_id)
    assert window._submitting_restart is None
    if outcome != "busy":
        assert invalidations == [] and protocol_pool.jobs == []
        if origin == "saved":
            assert app_id in window._save_restart_pending
            assert window.views[app_id]._config_error_label.text() == "Configuration saved. Restart requested."
        # A qualified callback must ignore a different synchronous submission.
        window._submitting_restart = other_id
        try:
            window.supervisor_manager.action_completed.emit(
                f"restart {app_id}", outcome == "success", "terminal fixture"
            )
        finally:
            window._submitting_restart = None
    assert invalidations == [app_id]
    assert capability.protocol_support_generation(app_id) == before_generation + 1
    assert capability.protocol_support_generation(other_id) == other_generation
    assert len(protocol_pool.jobs) == 1
    job = protocol_pool.jobs[0]
    assert job.meta.id == app_id and job.generation == before_generation + 1
    assert app_id not in window._save_restart_pending
    if origin == "saved":
        message = "busy fixture" if outcome == "busy" else "terminal fixture"
        assert window.views[app_id]._config_error_label.text() == (
            "service restart succeeded" if outcome == "success" else
            f"Configuration saved, but service restart failed: {message}"
        )
        assert warnings == []
    else:
        assert len(warnings) == (outcome != "success")
    # Re-probing cannot clear recovery blocks or change any current draft field.
    window._load_failed[app_id] = True
    window._baseline_conflict[app_id] = ("api_key",)
    window.views[app_id].set_recovery_state(load_failed=True, conflicts=("api_key",))
    job.signals.probe_finished.emit(app_id, supported())
    qtbot.waitUntil(lambda: not window._protocol_probe_jobs)
    assert window.views[app_id].get_current_draft() == before_draft
    assert window._draft_configs[app_id] == before_draft
    assert window._saved_configs[app_id] == before_saved
    assert window._snapshots[app_id] is snapshot and path.read_bytes() == before_bytes
    assert window._is_dirty(app_id)
    assert window._load_failed[app_id] and window._baseline_conflict[app_id] == ("api_key",)
    assert not window.views[app_id]._save_only_btn.isEnabled()


def test_save_only_polling_and_unrelated_restarts_do_not_invalidate(
    endpoint_window, protocol_pool, monkeypatch
):
    window = endpoint_window
    before = {app_id: capability.protocol_support_generation(app_id) for app_id in window.apps}
    window._on_supervisor_status(mw.SupervisorStatus(is_running=False))
    window.supervisor_manager.refresh_status()
    window._on_save_requested("ai-grammar", window.views["ai-grammar"].get_current_draft(), False)
    for app_id in ("chat2api", "file-bridge", "yt2txt"):
        window._on_restart_requested(app_id)
        window.supervisor_manager.action_completed.emit(f"restart {app_id}", True, "fixture")
        window._request_saved_restart(app_id)
        window.supervisor_manager.action_completed.emit(f"restart {app_id}", False, "fixture")
    assert before == {app_id: capability.protocol_support_generation(app_id) for app_id in window.apps}
    assert protocol_pool.jobs == []
    assert not window._save_restart_pending


def test_failed_to_start_clears_saved_pending_and_reprobes_exactly_once(
    qtbot, endpoint_window, protocol_pool, monkeypatch
):
    from tests.test_supervisor import ControlledActionProcess
    import ai_manager.services.supervisor as supervisor

    window = endpoint_window
    app_id = "ai-grammar"
    before = pending_protocol_draft(window, app_id, raw=True)
    generation = capability.protocol_support_generation(app_id)
    monkeypatch.setattr(supervisor, "QProcess", ControlledActionProcess)
    manager = supervisor.SupervisorManager(window.workspace_root, window)
    window.supervisor_manager = manager
    manager.action_completed.connect(window._on_supervisor_action)
    window._request_saved_restart(app_id)
    assert app_id in window._save_restart_pending
    assert protocol_pool.jobs == []
    process = manager._action_process
    process.fail_to_start()
    assert app_id not in window._save_restart_pending
    assert window.views[app_id]._config_error_label.text() == (
        "Configuration saved, but service restart failed: missing launcher fixture"
    )
    assert capability.protocol_support_generation(app_id) == generation + 1
    assert len(protocol_pool.jobs) == 1
    process.finish(1)
    assert capability.protocol_support_generation(app_id) == generation + 1
    assert len(protocol_pool.jobs) == 1
    assert window.views[app_id].get_current_draft() == window._draft_configs[app_id] == before


def install_saved(window, app_id, config, *, present=True, digest=b"b" * 32):
    snapshot = ConfigSnapshot(config, digest, present)
    window._snapshots[app_id] = snapshot
    window._saved_configs[app_id] = config.model_copy(deep=True)
    window._draft_configs[app_id] = config.model_copy(deep=True)
    window._load_failed[app_id] = False
    window._baseline_conflict[app_id] = ()
    window.views[app_id].load_config(snapshot)
    window.views[app_id].set_recovery_state(load_failed=False)
    return snapshot


def stage_draft(window, app_id, candidate):
    window.views[app_id]._display_draft(candidate)
    window._on_config_changed(app_id, candidate)


def owned_state(window, app_id="ai-grammar"):
    references = tuple(store.get(app_id) for store in (
        window._snapshots, window._saved_configs, window._draft_configs
    ))
    return references, copy.deepcopy(references)


def assert_owned_state(window, before, app_id="ai-grammar"):
    references, values = before
    current = tuple(store.get(app_id) for store in (
        window._snapshots, window._saved_configs, window._draft_configs
    ))
    assert all(now is previous for now, previous in zip(current, references))
    assert current == values


def test_gate_result_cannot_be_refused_and_no_op():
    with pytest.raises(ValueError):
        mw.LLMGateResult(refused=True, no_op=True)
    with pytest.raises(FrozenInstanceError):
        mw.LLMGateResult().no_op = True


def test_real_save_slot_obeys_gate_refusal(endpoint_window, monkeypatch):
    window = endpoint_window
    refused = mw.LLMGateResult(refused=True, message="fixture refusal", detail="<plain>")
    gate = Mock(return_value=refused)
    writer = Mock(side_effect=AssertionError("refused write"))
    monkeypatch.setattr(window, "_evaluate_llm_gate", gate)
    monkeypatch.setattr(mw, "write_app_config", writer)
    before = window._snapshots["ai-grammar"]
    draft = window.views["ai-grammar"].get_current_draft()
    window._on_save_requested("ai-grammar", draft, True)
    assert window.views["ai-grammar"]._config_error_label.text() == "fixture refusal"
    assert window.views["ai-grammar"]._config_error_details.toPlainText() == "<plain>"
    gate.assert_called_once_with("ai-grammar", draft, before.config)
    writer.assert_not_called()
    window.supervisor_manager.restart_service.assert_not_called()
    assert window._snapshots["ai-grammar"] is before


@pytest.mark.parametrize("case,message,detail", [
    ("missing_snapshot", "Reload the configuration before saving.", ""),
    ("failed_load", "Reload the configuration before saving.", ""),
    ("missing_saved", "Reload the configuration before saving.", ""),
    ("conflict", "Configuration changed while you were editing. Reload the configuration before saving.",
     "Conflicting fields: api_base, endpoint."),
    ("invalid_literal", "Unsupported protocol value: '/bad'. Pick one of the three supported protocols or Auto.", ""),
    ("raw_before_base", "Not one of the three supported protocols. Pick a valid one, or Auto to remove the key.",
     "Stored ai.endpoint: '<bad & raw>'"),
    ("raw_equal", "Not one of the three supported protocols. Pick a valid one, or Auto to remove the key.",
     "Stored ai.endpoint: '<bad & raw>'"),
    ("base_equal", "The protocol path already includes /v1. Enter the gateway prefix, e.g. https://api.openai.com.",
     "Request URL: https://x/v1/v1/messages"),
    ("base_changed", "The protocol path already includes /v1. Enter the gateway prefix, e.g. https://api.openai.com.",
     "Request URL: https://x/v1/v1/messages"),
    ("metadata_false", "Protocol selection is not available for this application.", ""),
])
def test_ordered_gate_refusals_retain_pending_state(endpoint_window, monkeypatch, case, message, detail):
    window = endpoint_window
    app_id = "ai-grammar"
    baseline = AppAIConfig(api_base="https://x", model="old")
    if case in ("base_equal", "base_changed"):
        baseline.endpoint = "/v1/messages"
    if case == "base_equal":
        baseline.api_base = "https://x/v1/"
    if case == "raw_equal":
        baseline.endpoint_raw = "'<bad & raw>'"
    old = install_saved(window, app_id, baseline)
    candidate = baseline.model_copy(deep=True)
    if case not in ("raw_equal", "base_equal"):
        candidate.model = "pending"
    if case in ("raw_before_base", "base_changed"):
        candidate.api_base = "https://x/v1/"
        candidate.endpoint = "/v1/messages"
    if case == "raw_before_base":
        candidate.endpoint_raw = "'<bad & raw>'"
    if case == "metadata_false":
        window.apps[app_id].supports_protocol_selection = False
        candidate.endpoint = "/v1/messages"
    # Forge bad base shape too: the literal guard must win over revalidation.
    if case in ("missing_snapshot", "failed_load", "missing_saved", "conflict", "invalid_literal"):
        candidate = AppAIConfig.model_construct(api_base=123, endpoint="/bad", model="pending")
        # This forged payload enters at the save boundary, bypassing widget validation.
        window._draft_configs[app_id] = candidate.model_copy(deep=True)
    elif case == "metadata_false":
        window._on_config_changed(app_id, candidate)
    else:
        stage_draft(window, app_id, candidate)
    if case == "missing_snapshot":
        window._snapshots.pop(app_id)
    elif case == "failed_load":
        window._load_failed[app_id] = True
    elif case == "missing_saved":
        window._saved_configs.pop(app_id)
    if case in ("missing_snapshot", "failed_load", "missing_saved", "conflict"):
        window._baseline_conflict[app_id] = ("api_base", "endpoint")
    before = owned_state(window)
    widgets_before = window.views[app_id].get_current_draft()
    path = window.apps[app_id].relative_path / "config.yaml"
    raw = path.read_bytes()
    writer = Mock(side_effect=AssertionError("refusal reached writer"))
    probe = Mock(side_effect=AssertionError("early guard reached probe"))
    monkeypatch.setattr(mw, "write_app_config", writer)
    monkeypatch.setattr(mw, "probe_protocol_support", probe)
    support_before = window._protocol_support[app_id]
    window._on_save_requested(app_id, candidate, True)
    view = window.views[app_id]
    assert view._config_error_label.text() == message
    assert view._config_error_details.toPlainText() == detail
    assert view._config_error_label.textFormat() is Qt.TextFormat.PlainText
    assert_owned_state(window, before)
    assert view.get_current_draft() == widgets_before
    assert window._protocol_support[app_id] is support_before
    assert path.read_bytes() == raw
    assert not list(path.parent.glob("*.bak"))
    writer.assert_not_called()
    probe.assert_not_called()
    window.supervisor_manager.restart_service.assert_not_called()
    assert old.sha256 == b"b" * 32


@pytest.mark.parametrize("guard", ["load", "conflict"])
@pytest.mark.parametrize("should_restart", [False, True])
def test_equal_draft_still_obeys_recovery_guards(endpoint_window, monkeypatch, guard, should_restart):
    window = endpoint_window
    app_id = "ai-grammar"
    old = window._snapshots[app_id]
    window._load_failed[app_id] = guard == "load"
    window._baseline_conflict[app_id] = ("endpoint",) if guard == "conflict" else ()
    writer = Mock(side_effect=AssertionError("blocked equality wrote"))
    probe = Mock(side_effect=AssertionError("blocked equality probed"))
    monkeypatch.setattr(mw, "write_app_config", writer)
    monkeypatch.setattr(mw, "probe_protocol_support", probe)
    window._on_save_requested(app_id, old.config, should_restart)
    assert window.views[app_id]._config_error_label.text() == (
        "Reload the configuration before saving." if guard == "load" else
        "Configuration changed while you were editing. Reload the configuration before saving."
    )
    assert window._snapshots[app_id] is old
    writer.assert_not_called()
    probe.assert_not_called()
    window.supervisor_manager.restart_service.assert_not_called()


@pytest.mark.parametrize("status", [ProtocolSupportStatus.UNSUPPORTED, ProtocolSupportStatus.UNVERIFIABLE])
@pytest.mark.parametrize("removal", [True, False])
def test_removal_and_unchanged_skip_probe(endpoint_window, monkeypatch, status, removal):
    window = endpoint_window
    old = install_saved(window, "ai-grammar", AppAIConfig(api_base="https://x", endpoint="/v1/messages"))
    forbidden = Mock(side_effect=AssertionError("preserved/removed endpoint probed"))
    monkeypatch.setattr(mw, "probe_protocol_support", forbidden)
    window._protocol_support["ai-grammar"] = ProtocolSupport(status, frozenset(), "unknown detail")
    candidate = AppAIConfig.model_validate({**old.config.model_dump(), "model": "pending",
                                           "endpoint": None if removal else old.config.endpoint})
    stage_draft(window, "ai-grammar", candidate)
    writer = Mock(return_value=b"n" * 32)
    monkeypatch.setattr(mw, "write_app_config", writer)
    window._on_save_requested("ai-grammar", candidate, False)
    writer.assert_called_once_with(window.apps["ai-grammar"], candidate,
                                   baseline=old.config, expected_sha256=old.sha256)
    assert window._snapshots["ai-grammar"].sha256 == b"n" * 32
    assert window._saved_configs["ai-grammar"] == candidate
    forbidden.assert_not_called()


@pytest.mark.parametrize("status,endpoint,old_endpoint,allowed", [
    (ProtocolSupportStatus.SUPPORTED, "/v1/responses", None, True),
    (ProtocolSupportStatus.PARTIAL, "/v1/messages", None, True),
    (ProtocolSupportStatus.PARTIAL, "/v1/responses", "/v1/messages", False),
    (ProtocolSupportStatus.UNSUPPORTED, "/v1/messages", None, False),
    (ProtocolSupportStatus.UNVERIFIABLE, "/v1/messages", None, False),
    (ProtocolSupportStatus.UNVERIFIABLE, "/v1/responses", "/v1/messages", False),
])
def test_changed_endpoint_uses_fresh_acceptance(endpoint_window, monkeypatch, status, endpoint, old_endpoint, allowed):
    window = endpoint_window
    app_id = "ai-grammar"
    old = install_saved(window, app_id, AppAIConfig(api_base="https://x", endpoint=old_endpoint))
    candidate = AppAIConfig.model_validate({**old.config.model_dump(), "endpoint": endpoint, "model": "pending"})
    stage_draft(window, app_id, candidate)
    before = owned_state(window)
    accepted = ENDPOINT_VALUES if status is ProtocolSupportStatus.SUPPORTED else (
        frozenset({"/v1/messages"}) if status is ProtocolSupportStatus.PARTIAL else frozenset()
    )
    fresh = ProtocolSupport(status, accepted, "<probe> api_key='fresh-secret'")
    # The displayed result deliberately disagrees with the keyed lookup.
    window._protocol_support[app_id] = (
        ProtocolSupport(ProtocolSupportStatus.UNSUPPORTED) if allowed else supported()
    )
    probe = Mock(return_value=fresh)
    writer = Mock(return_value=b"n" * 32, side_effect=None if allowed else AssertionError("rejected write"))
    monkeypatch.setattr(mw, "probe_protocol_support", probe)
    monkeypatch.setattr(mw, "write_app_config", writer)
    window._on_save_requested(app_id, candidate, False)
    view = window.views[app_id]
    if allowed:
        assert window._snapshots[app_id].config == candidate
        assert window._snapshots[app_id].sha256 == b"n" * 32
        writer.assert_called_once_with(window.apps[app_id], candidate,
                                       baseline=old.config, expected_sha256=old.sha256)
    else:
        assert view._config_error_label.text() == (
            "Cannot verify this build; introducing or changing ai.endpoint is refused. Select Auto to remove the key, or restore the saved protocol."
            if status is ProtocolSupportStatus.UNVERIFIABLE else
            f"Installed build rejected protocol {endpoint}. Update the service or select Auto."
        )
        assert_owned_state(window, before)
        assert view.get_current_draft() == candidate
        assert view._protocol_combo.currentData() == endpoint
        writer.assert_not_called()
    probe.assert_called_once_with(window.apps[app_id])
    assert window._protocol_support[app_id] is fresh and view._protocol_support is fresh
    if status is ProtocolSupportStatus.SUPPORTED:
        assert view._config_error_details.toPlainText() == ""
    else:
        assert view._config_error_details.toPlainText() == fresh.detail
    assert "fresh-secret" not in fresh.detail
    window.supervisor_manager.restart_service.assert_not_called()


@pytest.mark.parametrize("should_restart", [False, True])
@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize("source", [
    b'# odd spacing\nai: {api_base: "https://x", model: "old", temperature: 0.2} # keep\n',
    b"# omitted managed leaves\nai: { messages_default_max_tokens: 8192 }\n",
])
def test_no_op_skips_all_file_operations(endpoint_window, monkeypatch, should_restart, read_only, source):
    window = endpoint_window
    app_id = "ai-grammar"
    path = window.apps[app_id].relative_path / "config.yaml"
    path.write_bytes(source)
    path.chmod(0o440 if read_only else 0o640)
    window._load_config(app_id)
    before = owned_state(window)
    mode = stat.S_IMODE(path.stat().st_mode)
    entries = set(path.parent.iterdir())
    forbidden = Mock(side_effect=AssertionError("no-op reached file operation"))
    monkeypatch.setattr(mw, "write_app_config", forbidden)
    monkeypatch.setattr(mw, "probe_protocol_support", forbidden)
    monkeypatch.setattr(yaml_manager, "render_app_config", forbidden)
    monkeypatch.setattr(transaction_module, "Transaction", forbidden)
    window._on_save_requested(app_id, window.views[app_id].get_current_draft(), should_restart)
    assert window.views[app_id]._config_error_label.text() == (
        "Configuration saved. Restart requested." if should_restart else "Configuration saved."
    )
    assert_owned_state(window, before)
    forbidden.assert_not_called()
    assert path.read_bytes() == source and stat.S_IMODE(path.stat().st_mode) == mode
    assert set(path.parent.iterdir()) == entries
    if should_restart:
        window.supervisor_manager.restart_service.assert_called_once_with(app_id)
    else:
        window.supervisor_manager.restart_service.assert_not_called()


@pytest.mark.parametrize("raw_value", [b'"/bad"', b"null", b"''", b"1", b"false"])
def test_explicit_raw_repair_to_auto_reaches_real_writer(endpoint_window, monkeypatch, raw_value):
    window = endpoint_window
    app_id = "ai-grammar"
    path = window.apps[app_id].relative_path / "config.yaml"
    path.write_bytes(b"ai:\n  api_base: https://x\n  model: old\n  endpoint: " + raw_value + b"\n")
    window._load_config(app_id)
    old = window._snapshots[app_id]
    assert old.config.endpoint is None and old.config.endpoint_raw is not None
    view = window.views[app_id]
    view._protocol_combo.setCurrentIndex(0)
    candidate = view.get_current_draft()
    assert candidate.endpoint is None and candidate.endpoint_raw is None
    writer = Mock(wraps=mw.write_app_config)
    probe = Mock(side_effect=AssertionError("raw removal probed"))
    monkeypatch.setattr(mw, "write_app_config", writer)
    monkeypatch.setattr(mw, "probe_protocol_support", probe)
    window._on_save_requested(app_id, candidate, False)
    writer.assert_called_once_with(window.apps[app_id], candidate,
                                   baseline=old.config, expected_sha256=old.sha256)
    assert b"endpoint" not in path.read_bytes()
    assert window._snapshots[app_id].sha256 == sha256(path.read_bytes()).digest()
    assert window._snapshots[app_id].config.endpoint_raw is None
    probe.assert_not_called()


def test_other_forged_shape_uses_local_save_error(endpoint_window, monkeypatch):
    window = endpoint_window
    old = owned_state(window)
    writer = Mock(side_effect=AssertionError("invalid shape wrote"))
    probe = Mock(side_effect=AssertionError("invalid shape probed"))
    failures = Mock(wraps=window._on_structured_save_failed)
    monkeypatch.setattr(mw, "write_app_config", writer)
    monkeypatch.setattr(mw, "probe_protocol_support", probe)
    monkeypatch.setattr(window, "_on_structured_save_failed", failures)
    candidate = AppAIConfig.model_construct(api_base=123, endpoint="/v1/messages")
    window._on_save_requested("ai-grammar", candidate, True)
    error = failures.call_args.args[1]
    assert type(error) is ConfigError
    assert str(error).startswith("Configuration save failed: ") and "api_base" in str(error)
    assert_owned_state(window, old)
    writer.assert_not_called()
    probe.assert_not_called()
    window.supervisor_manager.restart_service.assert_not_called()


def test_two_saves_advance_actual_digest_and_presence(endpoint_window, monkeypatch):
    window = endpoint_window
    app_id = "ai-grammar"
    path = window.apps[app_id].relative_path / "config.yaml"
    path.write_bytes(b"# intentional defaults\nai: {messages_default_max_tokens: 8192}\n")
    window._load_config(app_id)
    old = window._snapshots[app_id]
    writer = Mock(wraps=mw.write_app_config)
    probe = Mock(return_value=supported())
    monkeypatch.setattr(mw, "write_app_config", writer)
    monkeypatch.setattr(mw, "probe_protocol_support", probe)
    view = window.views[app_id]
    view._protocol_combo.setCurrentIndex(view._protocol_combo.findData("/v1/messages"))
    window._on_save_requested(app_id, view.get_current_draft(), False)
    first = window._snapshots[app_id]
    assert first.sha256 == sha256(path.read_bytes()).digest() and first.sha256 != old.sha256
    assert first.api_base_present is False and b"api_base" not in path.read_bytes()
    assert view._request_url_label.text() == "Request URL: https://api.openai.com/v1/messages"
    for model, base in (("model-one", "https://explicit"), ("model-two", "https://explicit")):
        previous = window._snapshots[app_id]
        previous_bytes = path.read_bytes()
        view._model_combo.setEditText(model)
        view._base_url_edit.setText(base)
        candidate = view.get_current_draft()
        window._on_save_requested(app_id, candidate, False)
        current = window._snapshots[app_id]
        assert writer.call_args.kwargs["expected_sha256"] == sha256(previous_bytes).digest() == previous.sha256
        assert writer.call_args.kwargs["baseline"] is previous.config
        assert current.sha256 == sha256(path.read_bytes()).digest() != previous.sha256
        assert current.config == candidate and current.api_base_present is True
        assert view._request_url_label.text() == "Request URL: https://explicit/v1/messages"
        assert window._saved_configs[app_id] == window._draft_configs[app_id] == candidate
        assert len({id(current.config), id(window._saved_configs[app_id]), id(window._draft_configs[app_id])}) == 3
    assert writer.call_count == 3
    probe.assert_called_once_with(window.apps[app_id])
    window.supervisor_manager.restart_service.assert_not_called()


@pytest.mark.parametrize("failure", ["local", "copy", "restored", "unknown"])
def test_precommit_failure_retains_all_owned_values(endpoint_window, monkeypatch, failure):
    window = endpoint_window
    app_id = "ai-grammar"
    view = window.views[app_id]
    view._model_combo.setEditText("pending")
    candidate = view.get_current_draft()
    before = owned_state(window)
    path = window.apps[app_id].relative_path / "config.yaml"
    raw = path.read_bytes()
    report = TransactionReport(phase="rollback", files={path: "unknown" if failure == "unknown" else "restored"},
                               error="primary transaction fixture")
    error = TransactionError(report) if failure in ("restored", "unknown") else OSError("precommit fixture")
    writer = Mock(side_effect=error)
    dialog = Mock()
    monkeypatch.setattr(mw, "write_app_config", writer)
    monkeypatch.setattr(mw, "TransactionReportDialog", dialog)
    if failure == "copy":
        def broken_copy(*args, **kwargs):
            raise RecursionError("precommit copy fixture")
        monkeypatch.setattr(AppAIConfig, "model_copy", broken_copy)
    window._on_save_requested(app_id, candidate, True)
    assert_owned_state(window, before)
    assert path.read_bytes() == raw and view.get_current_draft() == candidate
    assert window._load_failed[app_id] is (failure == "unknown")
    assert view._save_only_btn.isEnabled() is (failure != "unknown")
    assert view._save_restart_btn.isEnabled() is (failure != "unknown")
    assert view._reload_btn.isHidden() is (failure != "unknown")
    if failure in ("restored", "unknown"):
        dialog.assert_called_once_with(report, window)
        assert "primary transaction fixture" in view._config_error_label.text()
    else:
        assert view._config_error_label.text().startswith("Configuration save failed: ")
    if failure == "copy":
        writer.assert_not_called()
    if failure == "unknown":
        writer.reset_mock()
        window._on_save_requested(app_id, candidate, False)
        writer.assert_not_called()
    window.supervisor_manager.restart_service.assert_not_called()


def test_stale_save_uses_llm_recovery_and_retains_external_bytes(endpoint_window, monkeypatch):
    window = endpoint_window
    app_id = "ai-grammar"
    view = window.views[app_id]
    view._model_combo.setEditText("pending")
    candidate = view.get_current_draft()
    before = owned_state(window)
    path = window.apps[app_id].relative_path / "config.yaml"
    external = path.read_bytes() + b"# external edit\n"
    external = external.replace(b"ai:\n", b"ai:\n  endpoint: /v1/messages\n")
    path.write_bytes(external)
    stale_dialog = Mock()
    monkeypatch.setattr(mw, "StaleDocumentDialog", stale_dialog)
    failures = Mock(wraps=window._on_structured_save_failed)
    monkeypatch.setattr(window, "_on_structured_save_failed", failures)
    window._on_save_requested(app_id, candidate, True)
    assert view._config_error_label.text() == "Configuration changed on disk; save refused. Reload the configuration before saving."
    error = failures.call_args.args[1]
    assert isinstance(error, StaleDocumentError)
    assert error.expected_sha256 == before[0][0].sha256 and error.actual_sha256 == sha256(external).digest()
    assert_owned_state(window, before)
    assert view.get_current_draft() == candidate and path.read_bytes() == external
    assert window._load_failed[app_id] and not view._reload_btn.isHidden()
    assert not view._save_only_btn.isEnabled() and not view._save_restart_btn.isEnabled()
    stale_dialog.assert_not_called()
    assert not list(path.parent.glob("*.bak"))
    support = supported()
    token = 1
    generation = capability.protocol_support_generation(app_id)
    window._protocol_probe_tokens[app_id] = token
    window._on_protocol_probe_finished(app_id, token, generation, support)
    assert window._load_failed[app_id]
    assert view._config_error_label.text() == (
        "Configuration changed on disk; save refused. Reload the configuration before saving."
    )
    assert window._protocol_support[app_id] is support
    assert view._protocol_support is support

    question = Mock(return_value=QMessageBox.StandardButton.Discard)
    monkeypatch.setattr(mw.QMessageBox, "question", question)
    window._reload_config(app_id)
    question.assert_called_once()
    assert window._snapshots[app_id].sha256 == sha256(external).digest()
    assert window._snapshots[app_id].api_base_present is True
    assert window._draft_configs[app_id] == view.get_current_draft()
    assert view.get_current_draft().endpoint == "/v1/messages"
    assert not window._load_failed[app_id]
    assert not window._baseline_conflict[app_id]
    assert view._save_only_btn.isEnabled() and view._save_restart_btn.isEnabled()
    assert not window._is_dirty(app_id)
    assert window._protocol_support[app_id] is support
    assert view._protocol_support is support
    window.supervisor_manager.restart_service.assert_not_called()


@pytest.mark.parametrize("typed", [False, True])
def test_coordinator_installs_committed_cleanup_outcome(endpoint_window, monkeypatch, typed):
    window = endpoint_window
    app_id = "ai-grammar"
    view = window.views[app_id]
    view._model_combo.setEditText("committed-fixture")
    view._base_url_edit.setText("https://committed")
    candidate = view.get_current_draft()
    old = window._snapshots[app_id]
    path = window.apps[app_id].relative_path / "config.yaml"
    actual_writer = mw.write_app_config
    displays = Mock(wraps=view.load_config)
    monkeypatch.setattr(view, "load_config", displays)
    if typed:
        def writer(meta, value, *, baseline, expected_sha256):
            digest = actual_writer(meta, value, baseline=baseline, expected_sha256=expected_sha256)
            raise CommittedWriteError(path, digest, TransactionReport(phase="complete", files={path: "new"}, committed=True),
                                      OSError("post-commit unlock fixture"))
        monkeypatch.setattr(mw, "write_app_config", writer)
    else:
        original_exit = Transaction.__exit__
        def failing_exit(self, kind, error, tb):
            result = original_exit(self, kind, error, tb)
            if error is None:
                raise OSError("post-commit unlock fixture")
            return result
        monkeypatch.setattr(Transaction, "__exit__", failing_exit)
    window._on_save_requested(app_id, candidate, True)
    installed = window._snapshots[app_id]
    assert b"committed-fixture" in path.read_bytes()
    assert installed.sha256 == sha256(path.read_bytes()).digest()
    assert installed is not old and installed.config == candidate and installed.api_base_present is True
    assert window._saved_configs[app_id] == window._draft_configs[app_id] == candidate
    assert len({id(installed.config), id(window._saved_configs[app_id]), id(window._draft_configs[app_id])}) == 3
    assert old.config.model == "original-grammar"
    assert view._config_error_label.text() == "Configuration saved, but the file must be reloaded before another save."
    assert view._config_error_details.toPlainText() == "post-commit unlock fixture"
    assert window._load_failed[app_id] and not view._reload_btn.isHidden()
    assert not view._save_only_btn.isEnabled() and not view._save_restart_btn.isEnabled()
    displays.assert_not_called()
    window.supervisor_manager.restart_service.assert_not_called()
    # A second submission cannot use the committed error as permission to write again.
    forbidden = Mock(side_effect=AssertionError("save after committed cleanup failure"))
    monkeypatch.setattr(mw, "write_app_config", forbidden)
    window._on_save_requested(app_id, candidate, True)
    forbidden.assert_not_called()
    assert window._snapshots[app_id] is installed


@pytest.mark.parametrize("display_seam", ["load_config", "dirty", "auth", "late_copy"])
def test_post_commit_display_failure_retains_committed_snapshot(endpoint_window, monkeypatch, display_seam):
    window = endpoint_window
    app_id = "ai-grammar"
    path = window.apps[app_id].relative_path / "config.yaml"
    path.write_bytes(b"ai: {model: original}\n")
    window._load_config(app_id)
    old = window._snapshots[app_id]
    view = window.views[app_id]
    view._model_combo.setEditText("committed-display-fixture")
    view._base_url_edit.setText("https://explicit")
    candidate = view.get_current_draft()
    if display_seam == "late_copy":
        actual_writer = mw.write_app_config
        actual_copy = AppAIConfig.model_copy
        def fail_copy(*args, **kwargs):
            raise RecursionError("display fixture")
        def writer(*args, **kwargs):
            digest = actual_writer(*args, **kwargs)
            monkeypatch.setattr(AppAIConfig, "model_copy", fail_copy)
            return digest
        monkeypatch.setattr(mw, "write_app_config", writer)
    else:
        broken = Mock(side_effect=RuntimeError("display fixture"))
        if display_seam == "load_config":
            monkeypatch.setattr(view, "load_config", broken)
        else:
            monkeypatch.setattr(window, "_set_dirty_indicator" if display_seam == "dirty" else "_update_auth_warnings", broken)
    unexpected = None
    try:
        window._on_save_requested(app_id, candidate, True)
    except Exception as exc:
        unexpected = exc
    installed = window._snapshots[app_id]
    assert b"committed-display-fixture" in path.read_bytes()
    assert installed.sha256 == sha256(path.read_bytes()).digest()
    assert installed is not old and installed.config == candidate and installed.api_base_present is True
    assert window._saved_configs[app_id] == window._draft_configs[app_id] == candidate
    assert len({id(installed.config), id(window._saved_configs[app_id]), id(window._draft_configs[app_id])}) == 3
    assert window._load_failed[app_id] and not view._save_only_btn.isEnabled()
    assert not view._save_restart_btn.isEnabled() and not view._reload_btn.isHidden()
    assert view._config_error_label.text() == "Configuration saved, but the file must be reloaded before another save."
    assert view._config_error_details.toPlainText() == "display fixture"
    assert old.api_base_present is False and old.config.model == "original"
    assert unexpected is None
    window.supervisor_manager.restart_service.assert_not_called()
    if display_seam == "late_copy":
        monkeypatch.setattr(AppAIConfig, "model_copy", actual_copy)


def test_primary_unknown_transaction_error_survives_cleanup_at_save_seam(endpoint_window, monkeypatch):
    window = endpoint_window
    app_id = "ai-grammar"
    view = window.views[app_id]
    view._model_combo.setEditText("pending")
    candidate = view.get_current_draft()
    before = owned_state(window)
    path = window.apps[app_id].relative_path / "config.yaml"
    original_replace, original_release, original_sync = (
        Transaction.replace_all, Transaction._release, Transaction._fsync_dir
    )
    observed = []

    def failing_replace(tx):
        try:
            return original_replace(tx)
        except TransactionError as exc:
            observed.append(exc)
            raise

    def failing_sync(tx, parent):
        if tx._state in ("replacing", "rolling-back"):
            raise OSError("replace/restore fsync fixture")
        return original_sync(tx, parent)

    def failing_release(tx):
        original_release(tx)
        raise OSError("cleanup fixture")

    monkeypatch.setattr(Transaction, "replace_all", failing_replace)
    monkeypatch.setattr(Transaction, "_fsync_dir", failing_sync)
    monkeypatch.setattr(Transaction, "_release", failing_release)
    failures = Mock(wraps=window._on_structured_save_failed)
    dialog = Mock()
    monkeypatch.setattr(window, "_on_structured_save_failed", failures)
    monkeypatch.setattr(mw, "TransactionReportDialog", dialog)
    window._on_save_requested(app_id, candidate, True)
    assert window._load_failed[app_id]
    assert len(observed) == 1
    primary = observed[0]
    assert failures.call_args.args[1] is primary and primary.report.files == {path: "unknown"}
    assert isinstance(primary.__cause__, OSError) and str(primary.__cause__) == "cleanup fixture"
    dialog.assert_called_once_with(primary.report, window)
    assert_owned_state(window, before)
    assert view.get_current_draft() == candidate
    assert not view._save_only_btn.isEnabled() and not view._save_restart_btn.isEnabled()
    assert not view._reload_btn.isHidden()
    assert view._config_error_label.text() == str(primary)
    window.supervisor_manager.restart_service.assert_not_called()
@pytest.mark.parametrize("answer,discard", [
    (QMessageBox.StandardButton.Cancel, False),
    (QMessageBox.StandardButton.Discard, True),
])
def test_changed_digest_pending_reload_requires_confirmation(
    endpoint_window, monkeypatch, answer, discard
):
    window = endpoint_window
    app_id = "ai-grammar"
    view = window.views[app_id]
    view._model_combo.setCurrentText("pending")
    before = window._snapshots[app_id]
    pending = view.get_current_draft()
    window._load_failed[app_id] = True
    path = window.apps[app_id].relative_path / "config.yaml"
    path.write_text("ai: {api_base: 'https://new', model: external, endpoint: /v1/messages}\n")
    question = Mock(return_value=answer)
    monkeypatch.setattr(mw.QMessageBox, "question", question)

    window._reload_config(app_id)

    question.assert_called_once()
    assert "Reload configuration" in question.call_args.args
    assert "Reload configuration and discard unsaved changes?" in question.call_args.args
    if discard:
        assert window._snapshots[app_id].sha256 == sha256(path.read_bytes()).digest()
        assert view.get_current_draft().model == "external"
        assert not window._is_dirty(app_id)
        assert not window._load_failed[app_id]
    else:
        assert window._snapshots[app_id] is before
        assert window._draft_configs[app_id] == pending == view.get_current_draft()
        assert window._load_failed[app_id]
    question.side_effect = None
    question.return_value = QMessageBox.StandardButton.Discard



def test_same_digest_reload_preserves_pending_edits(endpoint_window, monkeypatch):
    window = endpoint_window
    app_id = "ai-grammar"
    view = window.views[app_id]
    view._model_combo.setCurrentText("pending-model")
    before = window._snapshots[app_id]
    pending = view.get_current_draft()
    window._load_failed[app_id] = True
    question = Mock(side_effect=AssertionError("same digest must not prompt"))
    writer = Mock(side_effect=AssertionError("reload writes"))
    monkeypatch.setattr(mw.QMessageBox, "question", question)
    monkeypatch.setattr(mw, "write_app_config", writer)

    window._reload_config(app_id)

    assert window._snapshots[app_id] is not before
    assert window._snapshots[app_id].sha256 == before.sha256
    assert window._draft_configs[app_id] == pending == view.get_current_draft()
    assert not window._load_failed[app_id]
    assert view._save_only_btn.isEnabled() and view._save_restart_btn.isEnabled()
    question.assert_not_called()
    writer.assert_not_called()
    question.side_effect = None
    question.return_value = QMessageBox.StandardButton.Discard



def test_changed_digest_clean_reload_installs_without_confirmation(endpoint_window, monkeypatch):
    window = endpoint_window
    app_id = "ai-grammar"
    path = window.apps[app_id].relative_path / "config.yaml"
    path.write_text("ai: {api_base: 'https://new', model: external, endpoint: /v1/messages}\n")
    question = Mock(side_effect=AssertionError("clean reload must not prompt"))
    monkeypatch.setattr(mw.QMessageBox, "question", question)

    window._reload_config(app_id)

    incoming_digest = sha256(path.read_bytes()).digest()
    view_draft = window.views[app_id].get_current_draft()
    assert window._snapshots[app_id].sha256 == incoming_digest
    assert window._draft_configs[app_id] == view_draft
    assert view_draft.model == "external" and view_draft.endpoint == "/v1/messages"
    assert not window._is_dirty(app_id)
    assert not window._load_failed[app_id]
    question.assert_not_called()
    question.side_effect = None
    question.return_value = QMessageBox.StandardButton.Discard


@pytest.mark.parametrize("answer,discard", [
    (QMessageBox.StandardButton.Cancel, False),
    (QMessageBox.StandardButton.Discard, True),
])
def test_equal_digest_conflict_requires_confirmation(endpoint_window, monkeypatch, answer, discard):
    window = endpoint_window
    app_id = "ai-grammar"
    view = window.views[app_id]
    view._model_combo.setCurrentText("pending")
    before = window._snapshots[app_id]
    pending = view.get_current_draft()
    conflicts = ("endpoint",)
    window._baseline_conflict[app_id] = conflicts
    view.set_recovery_state(load_failed=False, conflicts=conflicts)
    question = Mock(return_value=answer)
    monkeypatch.setattr(mw.QMessageBox, "question", question)

    window._reload_config(app_id)

    question.assert_called_once()
    if discard:
        assert window._snapshots[app_id] is not before
        assert window._snapshots[app_id].sha256 == before.sha256
        assert window._draft_configs[app_id] == view.get_current_draft() == before.config
        assert window._baseline_conflict[app_id] == ()
        assert not window._load_failed[app_id]
        assert view._save_only_btn.isEnabled() and view._save_restart_btn.isEnabled()
    else:
        assert window._snapshots[app_id] is before
        assert window._draft_configs[app_id] == pending == view.get_current_draft()
        assert window._baseline_conflict[app_id] == conflicts
        assert not view._save_only_btn.isEnabled() and not view._save_restart_btn.isEnabled()
    question.side_effect = None
    question.return_value = QMessageBox.StandardButton.Discard


@pytest.mark.parametrize("failure", ["read", "display", "copy"])
def test_failed_llm_reload_retains_owned_state_and_pending_widgets(
    endpoint_window, monkeypatch, failure
):
    window = endpoint_window
    app_id = "ai-grammar"
    view = window.views[app_id]
    view._model_combo.setCurrentText("pending")
    references = tuple(store[app_id] for store in (
        window._snapshots, window._saved_configs, window._draft_configs
    ))
    values = tuple(copy.deepcopy(value) for value in references)
    pending = view.get_current_draft()
    question = Mock(side_effect=AssertionError("failed reload must not prompt"))
    monkeypatch.setattr(mw.QMessageBox, "question", question)
    if failure == "read":
        monkeypatch.setattr(mw, "read_app_config_snapshot", Mock(side_effect=RuntimeError("read fixture")))
    elif failure == "display":
        monkeypatch.setattr(view, "load_config", Mock(side_effect=RuntimeError("display fixture")))
    else:
        original = mw.copy.deepcopy
        def fail_copy(value, *args, **kwargs):
            if isinstance(value, AppAIConfig):
                raise RecursionError("copy fixture")
            return original(value, *args, **kwargs)
        monkeypatch.setattr(mw.copy, "deepcopy", fail_copy)

    window._reload_config(app_id)

    current = tuple(store[app_id] for store in (
        window._snapshots, window._saved_configs, window._draft_configs
    ))
    assert all(now is old for now, old in zip(current, references))
    assert current == values
    assert window._load_failed[app_id]
    assert view.get_current_draft() == pending
    assert not view._save_only_btn.isEnabled() and not view._save_restart_btn.isEnabled()
    assert not view._reload_btn.isHidden()
    question.assert_not_called()
    question.side_effect = None
    question.return_value = QMessageBox.StandardButton.Discard


@pytest.mark.parametrize("endpoint_window", [broken_read], indirect=True)
def test_initial_failed_llm_reload_installs_snapshot_without_creating(
    endpoint_window, monkeypatch
):
    window = endpoint_window
    app_id = "ai-grammar"
    path = window.apps[app_id].relative_path / "config.yaml"
    path.write_text("ai: {model: recovered}\n")
    assert app_id not in window._snapshots
    assert window._load_failed[app_id]
    question = Mock(side_effect=AssertionError("initial reload must not prompt"))
    monkeypatch.setattr(mw.QMessageBox, "question", question)

    window._reload_config(app_id)

    assert window._snapshots[app_id].config.model == "recovered"
    assert window._draft_configs[app_id] == window.views[app_id].get_current_draft()
    assert not window._load_failed[app_id]
    assert window.views[app_id]._save_only_btn.isEnabled()
    question.assert_not_called()
    question.side_effect = None
    question.return_value = QMessageBox.StandardButton.Discard



def test_failed_llm_reload_does_not_copy_example(endpoint_window, monkeypatch):
    window = endpoint_window
    app_id = "ai-grammar"
    meta = window.apps[app_id]
    path = meta.relative_path / meta.config_file_name
    example = meta.relative_path / meta.example_config_file_name
    path.unlink()
    view = window.views[app_id]
    view._model_combo.setCurrentText("pending")
    old = window._snapshots[app_id]
    pending = view.get_current_draft()
    question = Mock(side_effect=AssertionError("read failure must not prompt"))
    monkeypatch.setattr(mw.QMessageBox, "question", question)

    window._reload_config(app_id)

    assert not path.exists() and example.exists()
    assert window._snapshots[app_id] is old
    assert window._draft_configs[app_id] == pending == view.get_current_draft()
    assert window._load_failed[app_id]
    question.assert_not_called()
    question.side_effect = None
    question.return_value = QMessageBox.StandardButton.Discard



def test_committed_failure_reload_retains_installed_snapshot_until_read_succeeds(
    endpoint_window, monkeypatch
):
    window = endpoint_window
    app_id = "ai-grammar"
    meta, view = window.apps[app_id], window.views[app_id]
    path = meta.relative_path / meta.config_file_name
    view._model_combo.setEditText("committed-reload")
    candidate = view.get_current_draft()
    actual_writer = mw.write_app_config

    def writer(metadata, value, *, baseline, expected_sha256):
        digest = actual_writer(metadata, value, baseline=baseline, expected_sha256=expected_sha256)
        raise CommittedWriteError(
            path,
            digest,
            TransactionReport(phase="complete", files={path: "new"}, committed=True),
            OSError("reload fixture"),
        )

    monkeypatch.setattr(mw, "write_app_config", writer)
    window._on_save_requested(app_id, candidate, False)
    installed = window._snapshots[app_id]
    assert window._load_failed[app_id]

    question = Mock(side_effect=AssertionError("failed read must not prompt"))
    monkeypatch.setattr(mw.QMessageBox, "question", question)
    monkeypatch.setattr(
        mw,
        "read_app_config_snapshot",
        Mock(side_effect=ConfigError("temporary reload failure")),
    )
    window._reload_config(app_id)
    assert window._snapshots[app_id] is installed
    assert window._draft_configs[app_id] == candidate
    assert window._load_failed[app_id]
    question.assert_not_called()
    question.side_effect = None
    question.return_value = QMessageBox.StandardButton.Discard

    monkeypatch.setattr(mw, "read_app_config_snapshot", read_app_config_snapshot)
    window._reload_config(app_id)
    assert window._snapshots[app_id] is not installed
    assert window._snapshots[app_id].sha256 == sha256(path.read_bytes()).digest()
    assert window._draft_configs[app_id] == view.get_current_draft()
    assert not window._load_failed[app_id]
    assert view._save_only_btn.isEnabled() and view._save_restart_btn.isEnabled()
