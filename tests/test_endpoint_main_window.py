"""Snapshot presentation and initial LLM ownership (save gate follows in Task 9)."""
from hashlib import sha256
from unittest.mock import Mock

import pytest

from ai_manager.config.models import AppAIConfig
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
