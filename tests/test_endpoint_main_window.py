"""Snapshot presentation and initial LLM ownership (save gate follows in Task 9)."""
from hashlib import sha256
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QProcess, QThread, QThreadPool
from PyQt6.QtWidgets import QApplication, QMessageBox

from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.models import AppAIConfig
from ai_manager.config.protocols import ENDPOINT_VALUES
from ai_manager.services import config_jobs as jobs
from ai_manager.services import protocol_capability as capability
from ai_manager.services.protocol_capability import ProtocolSupport, ProtocolSupportStatus
from ai_manager.config.yaml_manager import read_app_config_snapshot
from ai_manager.ui.app_detail_view import AppDetailView
from ai_manager.ui import main_window as mw


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
