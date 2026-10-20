"""Offscreen tests for the concrete review dialogs defined by Task 11.

Only ``ai_manager.ui.config_dialogs`` is covered here: the dialogs are
read-only, start with nothing selected, and never touch the filesystem.
"""

from dataclasses import replace
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QDialog, QLabel, QPlainTextEdit, QPushButton

from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.blast_radius import find_affected_dependents
from ai_manager.config.structured_config import load
from ai_manager.config.structured_models import (
    DependentMatch,
    Mutation,
    TransactionReport,
)
from ai_manager.ui.config_dialogs import (
    BlastRadiusDialog,
    ReviewChangesDialog,
    StaleDocumentDialog,
    TransactionReportDialog,
    _label,
)

BEFORE = b'{\n  "port": 8000\n}\n'
AFTER = b'{\n  "port": 8123\n}\n'


def blast_matches(workspace) -> tuple[DependentMatch, ...]:
    apps = get_managed_apps(workspace)
    before = load("chat2api", apps["chat2api"].relative_path / "config.json")
    after = replace(before, mutations=(Mutation(("server", "port"), "set", 8123),))
    return find_affected_dependents(apps, before, after)


def buttons(dialog) -> dict[str, QPushButton]:
    return {button.text(): button for button in dialog.findChildren(QPushButton)}


def label_texts(dialog) -> list[str]:
    return [label.text() for label in dialog.findChildren(QLabel)]


def test_review_changes_shows_added_and_removed_lines(qtbot):
    dialog = ReviewChangesDialog(BEFORE, AFTER, Path("/tmp/synthetic/config.json"))
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Review Changes"
    detail = dialog.findChild(QPlainTextEdit)
    assert detail.isReadOnly()
    diff = detail.toPlainText()
    assert "--- saved" in diff and "+++ draft" in diff
    assert '-  "port": 8000' in diff
    assert '+  "port": 8123' in diff
    assert "/tmp/synthetic/config.json" in label_texts(dialog)


def test_review_changes_does_not_write_the_document(qtbot, tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes(BEFORE)
    dialog = ReviewChangesDialog(path.read_bytes(), AFTER, path)
    qtbot.addWidget(dialog)
    assert path.read_bytes() == BEFORE
    buttons(dialog)["Close"].click()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_review_changes_tolerates_undecodable_bytes(qtbot):
    dialog = ReviewChangesDialog(b"\xff\xfe binary\n", b"\xff\xfe binary changed\n", Path("/tmp/x"))
    qtbot.addWidget(dialog)
    diff = dialog.findChild(QPlainTextEdit).toPlainText()
    assert " binary\n" in diff and " binary changed\n" in diff
    assert "\ufffd\ufffd" in diff


def test_blast_radius_starts_unchecked_and_returns_only_checked(qtbot, five_app_workspace):
    matches = blast_matches(five_app_workspace)
    assert [match.meta.id for match in matches] == ["ai-grammar", "textkit", "yt2txt"]
    dialog = BlastRadiusDialog(matches)
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Update dependent API base URLs?"
    checks = dialog.findChildren(QCheckBox)
    assert [check.text() for check in checks] == [
        f"{match.meta.display_name}: {match.old_api_base} \u2192 {match.new_api_base}"
        for match in matches
    ]
    assert not any(check.isChecked() for check in checks)
    assert dialog.selected_app_ids() == ()
    dialog._checks["ai-grammar"].setChecked(True)
    dialog._checks["yt2txt"].setChecked(True)
    assert dialog.selected_app_ids() == ("ai-grammar", "yt2txt")


def test_blast_radius_save_alone_returns_no_ids_even_when_checked(qtbot, five_app_workspace):
    dialog = BlastRadiusDialog(blast_matches(five_app_workspace))
    qtbot.addWidget(dialog)
    for check in dialog.findChildren(QCheckBox):
        check.setChecked(True)
    assert dialog.selected_app_ids() == ("ai-grammar", "textkit", "yt2txt")
    buttons(dialog)["Save chat2api Only"].click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.selected_app_ids() == ()


def test_blast_radius_cancel_rejects_and_selected_accepts(qtbot, five_app_workspace):
    cancel = BlastRadiusDialog(blast_matches(five_app_workspace))
    qtbot.addWidget(cancel)
    cancel.show()
    with qtbot.waitSignal(cancel.rejected, timeout=5000):
        buttons(cancel)["Cancel"].click()
    assert cancel.result() == QDialog.DialogCode.Rejected
    assert not cancel.isVisible()
    assert cancel.selected_app_ids() == ()

    accepted = BlastRadiusDialog(blast_matches(five_app_workspace))
    qtbot.addWidget(accepted)
    accepted.show()
    with qtbot.waitSignal(accepted.accepted, timeout=5000):
        buttons(accepted)["Save with Selected Updates"].click()
    assert accepted.result() == QDialog.DialogCode.Accepted
    assert not accepted.isVisible()
    assert accepted.selected_app_ids() == ()


def test_blast_radius_escapes_checkbox_mnemonics_and_keeps_labels_plain(qtbot, five_app_workspace):
    match = blast_matches(five_app_workspace)[1]
    renamed = replace(
        match,
        meta=match.meta.model_copy(update={"display_name": "Text & Kit"}),
        auth_warning="uses $TOKEN & friends",
    )
    dialog = BlastRadiusDialog((renamed,))
    qtbot.addWidget(dialog)
    check = dialog.findChild(QCheckBox)
    assert check.text().startswith("Text && Kit: ")
    assert "uses $TOKEN & friends" in label_texts(dialog)


def test_plain_labels_render_user_markup_literally(qtbot, five_app_workspace, tmp_path):
    markup = "<b>A & B</b>"

    helper = _label(markup, None)
    qtbot.addWidget(helper)
    assert helper.textFormat() == Qt.TextFormat.PlainText
    assert helper.text() == markup

    path = tmp_path / markup / "config.json"
    stale = StaleDocumentDialog(path)
    qtbot.addWidget(stale)
    stale_label = next(
        label for label in stale.findChildren(QLabel) if label.text() == str(path)
    )
    assert stale_label.textFormat() == Qt.TextFormat.PlainText
    assert stale_label.text() == str(path)
    assert "<b>A & B</b>" in stale_label.text()

    warning = "<b>A & B</b> & <i>C</i>"
    match = replace(blast_matches(five_app_workspace)[1], auth_warning=warning)
    dialog = BlastRadiusDialog((match,))
    qtbot.addWidget(dialog)
    warning_label = next(
        label for label in dialog.findChildren(QLabel) if label.text() == warning
    )
    assert warning_label.textFormat() == Qt.TextFormat.PlainText
    assert warning_label.text() == warning


def test_stale_document_defaults_to_cancel_and_reports_each_choice(qtbot, tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes(BEFORE)

    dialog = StaleDocumentDialog(path)
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Configuration Changed"
    assert dialog.choice() == "cancel"
    assert set(buttons(dialog)) == {"Reload", "Show diff", "Cancel"}
    assert "Configuration changed on disk; save refused." in label_texts(dialog)
    assert "Reload discards this app's unsaved draft." in label_texts(dialog)
    assert str(path) in label_texts(dialog)
    assert path.read_bytes() == BEFORE

    for text, token in (("Reload", "reload"), ("Show diff", "diff"), ("Cancel", "cancel")):
        each = StaleDocumentDialog(path)
        qtbot.addWidget(each)
        buttons(each)[text].click()
        assert each.choice() == token
        assert each.result() == QDialog.DialogCode.Accepted


def test_transaction_report_phase_summaries(qtbot, tmp_path):
    path = tmp_path / "config.json"
    other = tmp_path / "config.yaml"

    backups = TransactionReportDialog(
        TransactionReport(phase="backups", files={path: "unknown"})
    )
    qtbot.addWidget(backups)
    assert backups.windowTitle() == "Configuration Save Failed"
    assert (
        "Could not create all backups; no configuration files were changed."
        in label_texts(backups)
    )

    backup = tmp_path / "config.json.20261017T160734000000Z.4321-abcdef.bak"
    assert backup != path
    stage = TransactionReportDialog(
        TransactionReport(
            phase="stage",
            files={path: "unknown", other: "unknown"},
            backups={path: backup},
            error="stage failed: synthetic",
        )
    )
    qtbot.addWidget(stage)
    assert (
        "Could not stage configuration files; no configuration files were changed."
        in label_texts(stage)
    )
    details = stage.findChild(QPlainTextEdit)
    assert details.isReadOnly()
    text = details.toPlainText()
    assert f"{path}: unknown" in text
    assert f"{other}: unknown" in text
    assert f"Backup {path}: {backup}" in text.splitlines()
    assert "stage failed: synthetic" in text

    recovered = TransactionReportDialog(
        TransactionReport(phase="replace_all", files={path: "restored"})
    )
    qtbot.addWidget(recovered)
    assert (
        "Save failed; configuration files were restored from backups."
        in label_texts(recovered)
    )
    assert f"{path}: restored" in recovered.findChild(QPlainTextEdit).toPlainText()


def test_transaction_report_restore_failure_text_and_rows(qtbot, tmp_path):
    path = tmp_path / "config.json"
    report = TransactionReport(
        phase="rollback",
        files={path: "unknown"},
        backups={path: tmp_path / "config.json.bak"},
        restore_failures={path: "permission denied"},
        error="synthetic rollback error",
    )
    dialog = TransactionReportDialog(report)
    qtbot.addWidget(dialog)
    assert (
        "Save failed and some files could not be restored. Review every path "
        "below before restarting services."
        in label_texts(dialog)
    )
    text = dialog.findChild(QPlainTextEdit).toPlainText()
    assert f"{path}: permission denied" in text
    assert f"Backup {path}: {report.backups[path]}" in text.splitlines()
    assert (
        "Reload affected files after resolving the reported recovery failures." in text
    )
    assert "synthetic rollback error" in text
    buttons(dialog)["Close"].click()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_dialogs_accept_and_reject_cleanly_without_parent(qtbot, five_app_workspace, tmp_path):
    path = tmp_path / "config.json"
    dialogs = [
        ReviewChangesDialog(BEFORE, AFTER, path),
        BlastRadiusDialog(blast_matches(five_app_workspace)),
        StaleDocumentDialog(path),
        TransactionReportDialog(TransactionReport(phase="prepare")),
    ]
    for dialog in dialogs:
        qtbot.addWidget(dialog)
        assert dialog.parent() is None
        dialog.reject()
        assert dialog.result() == QDialog.DialogCode.Rejected
        dialog.accept()
        assert dialog.result() == QDialog.DialogCode.Accepted


# ---------------------------------------------------------------------------
# StructuredConfigView (Task 11, declarative view)
# ---------------------------------------------------------------------------

import json
import json
import os

import pytest
from PyQt6.QtCore import QMetaMethod
from PyQt6.QtWidgets import QComboBox, QGroupBox, QLineEdit, QTableWidget

from ai_manager.config.config_errors import (
    ConfigError,
    ConfigValidationError,
    UnknownConfigKindError,
)
from ai_manager.config.models import ServiceRunState, ServiceStatus
from ai_manager.config.structured_config import effective_mutations, render
from ai_manager.config.structured_models import LauncherProbeResult, ValidationResult
from ai_manager.services.supervisor import default_log_path
from ai_manager.ui.structured_config_view import PresenceControl, StructuredConfigView

SIGNALS = {
    "save_requested",
    "restart_requested",
    "config_changed",
    "fetch_models_requested",
}


def make_view(qtbot, workspace, app_id="chat2api"):
    """Build a loaded view for ``app_id`` and record everything it emits."""
    meta = get_managed_apps(workspace)[app_id]
    view = StructuredConfigView(meta)
    qtbot.addWidget(view)
    changes, saves, fetches, restarts = [], [], [], []
    view.config_changed.connect(lambda *args: changes.append(args))
    view.save_requested.connect(lambda *args: saves.append(args))
    view.fetch_models_requested.connect(lambda *args: fetches.append(args))
    view.restart_requested.connect(lambda *args: restarts.append(args))
    view.load_config(load(meta.config_kind, meta.relative_path / meta.config_file_name))
    return view, changes, saves, fetches, restarts


def bridge_path(workspace):
    meta = get_managed_apps(workspace)["file-bridge"]
    return meta.relative_path / meta.config_file_name


def group_titles(view):
    return [group.title() for view_group in view.findChildren(QGroupBox) for group in (view_group,)]


def test_view_declares_exactly_the_four_adapter_signals(qtbot, five_app_workspace):
    view, _, _, _, _ = make_view(qtbot, five_app_workspace)
    meta = view.metaObject()
    declared = {}
    for index in range(meta.methodOffset(), meta.methodCount()):
        method = meta.method(index)
        if method.methodType() == QMetaMethod.MethodType.Signal:
            declared[bytes(method.name()).decode()] = bytes(method.methodSignature()).decode()
    assert set(declared) == SIGNALS
    # PyQt6 exposes Python object payloads as ``PyQt_PyObject`` in the meta object.
    assert declared["fetch_models_requested"] == (
        "fetch_models_requested(PyQt_PyObject)"
    )
    assert declared["save_requested"] == "save_requested(QString,PyQt_PyObject,bool)"
    assert declared["restart_requested"] == "restart_requested(QString)"
    assert declared["config_changed"] == "config_changed(QString,PyQt_PyObject)"


def test_chat2api_construction_groups_fields_tabs_and_log_identity(qtbot, five_app_workspace):
    view, changed, saves, fetches, restarts = make_view(qtbot, five_app_workspace)
    assert group_titles(view) == ["Server", "Models"]
    assert set(view._fields) == {("server", "host"), ("server", "port"), ("server", "auth_token_env")}
    assert [view._tabs.tabText(i) for i in range(view._tabs.count())] == ["Configuration", "Logs"]
    assert view.log_view.service_id == "chat2api"
    assert view.log_view is view._tabs.widget(1)
    assert view._title_label.text() == "chat2api (Port 8000)"
    assert view._validation_label.text() == "Not validated since load."
    assert view._gate_label.text() == "Checking whether launcher honors config\u2026"
    assert view._table.rowCount() == 1 and view._table.columnCount() == 4
    assert [view._table.horizontalHeaderItem(i).text() for i in range(4)] == [
        "Name",
        "Provider",
        "Options",
        "Secrets",
    ]
    assert changed == saves == fetches == restarts == []


def test_file_bridge_has_exactly_three_fields_and_no_model_controls(qtbot, five_app_workspace):
    view, changed, saves, fetches, restarts = make_view(qtbot, five_app_workspace, "file-bridge")
    assert group_titles(view) == ["Save Location && Server"]
    assert set(view._fields) == {("save_root",), ("max_text_bytes",), ("port",)}
    assert [view._tabs.tabText(i) for i in range(view._tabs.count())] == ["Configuration", "Logs"]
    assert view.log_view.service_id == "file-bridge"
    assert not hasattr(view, "_table") and not hasattr(view, "_fetch_btn")
    assert view.findChildren(QTableWidget) == [] and view.findChildren(QComboBox) == []
    assert view._title_label.text() == "file-bridge (Port 8964)"
    # No host, auth or gate surface for the file bridge.
    assert ("server", "host") not in view._fields
    assert view._gate_label.text() == ""
    labels = [label.text() for label in view.findChildren(QLabel)]
    assert "Maximum text bytes (0 = no limit)" in labels
    assert "Save root" in labels and "Port" in labels
    assert changed == saves == fetches == restarts == []


def test_file_bridge_listener_is_never_gated_by_the_chat2api_launcher_rule(
    qtbot, five_app_workspace
):
    view, changed, saves, _, _ = make_view(qtbot, five_app_workspace, "file-bridge")
    view.set_launcher_gate(
        LauncherProbeResult(False, "fixture failure", stderr="fixture stderr\n")
    )
    assert view._gate_label.text() == ""
    assert view._fields[("port",)].isEnabled()
    view._fields[("port",)].edit.setText("8970")
    view._emit_save(True)
    assert [args[2] for args in saves] == [True]
    assert view._notice_label.text() == ""
    assert len(changed) == 1


def test_directory_field_offers_picker_and_only_edits_draft_text(qtbot, five_app_workspace):
    view, changed, _, _, _ = make_view(qtbot, five_app_workspace, "file-bridge")
    field = view._fields[("save_root",)]
    assert [button.text() for button in field.findChildren(QPushButton)] == ["Choose Directory"]
    field.edit.setText("/tmp/synthetic-save-root")
    assert len(changed) == 1
    draft = view.get_current_draft()
    assert effective_mutations(draft) == (
        _set(("save_root",), "/tmp/synthetic-save-root"),
    )
    assert not Path("/tmp/synthetic-save-root").exists()


def _set(address, value):
    from ai_manager.config.structured_models import Mutation

    return Mutation(address, "set", value)


def test_draft_round_trips_edits_and_absent_keys_stay_absent(qtbot, five_app_workspace):
    view, changed, _, fetches, _ = make_view(qtbot, five_app_workspace)
    view.set_launcher_gate(LauncherProbeResult(True))
    view._fields[("server", "port")].edit.setText("8123")
    view._fields[("server", "host")].edit.setText("localhost")
    view._fields[("server", "auth_token_env")].present.setChecked(False)
    assert len(changed) >= 2 and fetches == []
    tree = json.loads(render("chat2api", view.get_current_draft()))
    assert tree["server"]["port"] == 8123
    assert tree["server"]["host"] == "localhost"
    # Clearing "Present" deletes the key instead of writing an empty value.
    assert "auth_token_env" not in tree["server"]
    # The header shows the committed port, never the unsaved edit.
    assert view._title_label.text() == "chat2api (Port 8000)"
    # An untouched model route keeps no fabricated options mapping.
    assert "options" not in tree["models"]["echo-1"]


def test_nullable_auth_round_trips_between_null_and_absent(qtbot, five_app_workspace):
    view, _, _, _, _ = make_view(qtbot, five_app_workspace)
    field = view._fields[("server", "auth_token_env")]
    assert field.null.isChecked() and not field.edit.isEnabled()
    field.present.setChecked(False)
    assert "auth_token_env" not in json.loads(render("chat2api", view.get_current_draft()))["server"]
    field.present.setChecked(True)
    assert field.null.isChecked()
    field.null.setChecked(False)
    assert field.edit.isEnabled()
    field.edit.setText("SYNTHETIC_TOKEN")
    tree = json.loads(render("chat2api", view.get_current_draft()))
    assert tree["server"]["auth_token_env"] == "SYNTHETIC_TOKEN"
    field.null.setChecked(True)
    assert field.edit.isEnabled() is False
    assert json.loads(render("chat2api", view.get_current_draft()))["server"]["auth_token_env"] is None
    field.present.setChecked(False)
    assert "auth_token_env" not in json.loads(render("chat2api", view.get_current_draft()))["server"]


def test_save_buttons_emit_the_same_draft_with_distinct_restart_flags(qtbot, five_app_workspace):
    view, changed, saves, fetches, _ = make_view(qtbot, five_app_workspace)
    view.set_launcher_gate(LauncherProbeResult(True))
    view._fields[("server", "port")].edit.setText("8123")
    before = len(changed)
    view._save_only_btn.click()
    view._save_restart_btn.click()
    assert [args[0] for args in saves] == ["chat2api", "chat2api"]
    assert [args[2] for args in saves] == [False, True]
    assert saves[0][1] == saves[1][1] == view.get_current_draft()
    assert fetches == [] and len(changed) == before


def test_restart_button_emits_restart_request_without_a_draft(qtbot, five_app_workspace):
    view, changed, saves, fetches, restarts = make_view(qtbot, five_app_workspace)
    view._restart_btn.click()
    assert restarts == [("chat2api",)]
    assert changed == saves == fetches == []


def test_secret_reveal_never_marks_the_field_changed(qtbot, five_app_workspace):
    path = get_managed_apps(five_app_workspace)["chat2api"].relative_path / "config.json"
    data = json.loads(path.read_bytes())
    data["models"]["echo-1"]["options"] = {"password": "synthetic-password"}
    path.write_text(json.dumps(data), encoding="utf-8")
    view, changed, _, _, _ = make_view(qtbot, five_app_workspace)
    view._expand_model(view._model.rows[0].id)
    field = view._option_fields[("models", "echo-1", "options", "password")]
    assert field.edit.echoMode() == QLineEdit.EchoMode.Password
    assert not field.changed and field.edit.text() == "synthetic-password"
    field.reveal.setChecked(True)
    assert field.edit.echoMode() == QLineEdit.EchoMode.Normal
    field.reveal.setChecked(False)
    assert field.edit.echoMode() == QLineEdit.EchoMode.Password
    assert not field.changed
    assert effective_mutations(view.get_current_draft()) == ()
    assert changed == []
    # Only an explicit text edit writes the secret back.
    field.edit.setText("synthetic-rotated")
    assert field.changed
    assert effective_mutations(view.get_current_draft())[0].value == "synthetic-rotated"
    assert len(changed) == 1


def test_presence_control_preserves_invalid_loaded_integers_without_clamping(qtbot):
    field = PresenceControl("integer", True, "8964", parent=None)
    qtbot.addWidget(field)
    # A quoted integer loads as JSON so the string type stays visible.
    assert field.edit.text() == '"8964"' and field._raw_type
    written = []
    field.written.connect(lambda present, value: written.append((present, value)))
    field.edit.setText("9000")
    assert written[-1] == (True, 9000)

    raw = PresenceControl("integer", True, 8964.0, parent=None)
    qtbot.addWidget(raw)
    assert raw.edit.text() == "8964.0" and raw._raw_type
    raw.written.connect(lambda present, value: written.append((present, value)))
    raw.edit.setText("8964.7")
    assert written[-1] == (True, 8964.7)

    boolean = PresenceControl("integer", True, True, parent=None)
    qtbot.addWidget(boolean)
    assert boolean.edit.text() == "true" and boolean._raw_type

    plain = PresenceControl("integer", True, 8964, parent=None)
    qtbot.addWidget(plain)
    assert not plain._raw_type and plain.edit.text() == "8964"
    plain.written.connect(lambda present, value: written.append((present, value)))
    plain.edit.setText("not-a-number")
    assert written[-1] == (True, "not-a-number")
    plain.edit.setText("8123")
    assert written[-1] == (True, 8123)


def test_presence_control_absent_and_nullable_states(qtbot):
    absent = PresenceControl("text", False, None, default="127.0.0.1", parent=None)
    qtbot.addWidget(absent)
    assert absent.edit.text() == "127.0.0.1" and not absent.present.isChecked()
    assert not absent.edit.isEnabled()
    written = []
    absent.written.connect(lambda present, value: written.append((present, value)))
    absent.present.setChecked(True)
    assert written[-1] == (True, "127.0.0.1")
    absent.present.setChecked(False)
    assert written[-1] == (False, "127.0.0.1")

    authed = PresenceControl("nullable-text", True, None, parent=None)
    qtbot.addWidget(authed)
    assert authed.null.isChecked() and not authed.edit.isEnabled()
    authed.written.connect(lambda present, value: written.append((present, value)))
    authed.null.setChecked(False)
    assert written[-1] == (True, "")


def test_invalid_draft_types_are_reported_per_address(qtbot, five_app_workspace):
    from ai_manager.config.structured_config import _candidate
    from ai_manager.config.structured_schema import validate_in_process

    view, changed, saves, _, _ = make_view(qtbot, five_app_workspace)
    view.set_launcher_gate(LauncherProbeResult(True))
    view._fields[("server", "port")].edit.setText("eighty")
    draft = view.get_current_draft()
    assert draft.mutations[0].value == "eighty"
    assert effective_mutations(draft) == draft.mutations
    with pytest.raises(ConfigValidationError) as invalid:
        validate_in_process(
            "chat2api",
            _candidate(draft),
            config_path=draft.path,
            app_dir=view.app_meta.relative_path,
        )
    issues = invalid.value.issues
    assert [issue.address for issue in issues] == [("server", "port")]
    view.show_field_issues(issues)
    assert view._fields[("server", "port")].styleSheet() == "border: 1px solid #ef4444;"
    assert "Port must be an integer from 1 to 65535." in view._notice_label.text()
    assert "Configuration has invalid fields; nothing was saved." in view._notice_label.text()
    assert len(changed) == 1 and saves == []
    view._fields[("server", "port")].edit.setText("8123")
    assert view._notice_label.text() == ""
    assert view._fields[("server", "port")].styleSheet() == ""


def test_invalid_stored_port_is_reported_and_not_coerced(qtbot, five_app_workspace):
    path = get_managed_apps(five_app_workspace)["chat2api"].relative_path / "config.json"
    data = json.loads(path.read_bytes())
    data["server"]["port"] = "8000"
    path.write_text(json.dumps(data), encoding="utf-8")
    view, changed, _, _, _ = make_view(qtbot, five_app_workspace)
    assert view._title_label.text() == "chat2api (Port 8000)"
    assert view._fields[("server", "port")].edit.text() == '"8000"'
    assert "Port must be an integer from 1 to 65535." in view._notice_label.text()
    # The metadata default is only the displayed fallback, not a written value.
    assert effective_mutations(view.get_current_draft()) == ()
    assert changed == []


def test_raw_options_errors_open_the_editor_and_clear_afterwards(qtbot, five_app_workspace):
    view, _, _, _, _ = make_view(qtbot, five_app_workspace)
    row_id = view._model.rows[0].id
    view._expand_model(row_id)
    editor = view._row_issue_widgets[("models", "echo-1", "options")]
    toggle = view._raw_toggles[("models", "echo-1", "options")]
    assert isinstance(editor, QPlainTextEdit) and not toggle.isChecked()
    view._on_raw_options_changed(row_id, "{broken")
    assert toggle.isChecked() and editor.isVisibleTo(view)
    assert "Raw options must be a JSON object with unique keys." in view._notice_label.text()
    view._on_raw_options_changed(row_id, '{"future": 1}')
    assert view._notice_label.text() == ""
    assert json.loads(render("chat2api", view.get_current_draft()))["models"]["echo-1"]["options"] == {
        "future": 1
    }


def test_provider_change_warns_keeps_options_and_keeps_secret_fields(qtbot, five_app_workspace):
    path = get_managed_apps(five_app_workspace)["chat2api"].relative_path / "config.json"
    data = json.loads(path.read_bytes())
    data["models"]["echo-1"]["options"] = {"password": "synthetic-password", "prefix": "hi"}
    path.write_text(json.dumps(data), encoding="utf-8")
    view, changed, _, _, _ = make_view(qtbot, five_app_workspace)
    row_id = view._model.rows[0].id
    view._expand_model(row_id)
    view._table.cellWidget(0, 1).setCurrentText("browser")
    assert (
        view._provider_warning.text()
        == "Provider changed. Existing options were kept and may not apply to the new provider."
    )
    tree = json.loads(render("chat2api", view.get_current_draft()))
    assert tree["models"]["echo-1"]["provider"] == "browser"
    assert tree["models"]["echo-1"]["options"]["password"] == "synthetic-password"
    assert tree["models"]["echo-1"]["options"]["prefix"] == "hi"
    # A retained secret that the new provider does not declare stays masked.
    secret = view._option_fields[("models", "echo-1", "options", "password")]
    assert secret.edit.echoMode() == QLineEdit.EchoMode.Password
    assert view._table.cellWidget(0, 3).text() == "1 present"
    assert len(changed) == 1


def test_rename_and_remove_rows_address_exactly_one_route(qtbot, five_app_workspace):
    view, _, _, _, _ = make_view(qtbot, five_app_workspace)
    view._add_model()
    assert view.get_current_draft().input_issues[0].message == "Model names must be non-empty strings."
    new_row = view._table.rowCount() - 1
    view._table.item(new_row, 0).setText("new-echo")
    view._table.cellWidget(new_row, 1).setCurrentText("echo")
    view._option_changed(view._model.rows[-1].id, "prefix", True, "hello")
    tree = json.loads(render("chat2api", view.get_current_draft()))
    assert sorted(tree["models"]) == ["echo-1", "new-echo"]
    assert tree["models"]["new-echo"] == {"provider": "echo", "options": {"prefix": "hello"}}
    view._remove_model(view._model.rows[0].id)
    tree = json.loads(render("chat2api", view.get_current_draft()))
    assert list(tree["models"]) == ["new-echo"]


def test_launcher_gate_disables_only_listener_fields_with_exact_text(qtbot, five_app_workspace):
    view, changed, saves, _, _ = make_view(qtbot, five_app_workspace)
    assert view._gate_label.text() == "Checking whether launcher honors config\u2026"
    assert not view._fields[("server", "port")].isEnabled()
    assert not view._fields[("server", "host")].isEnabled()
    assert view._fields[("server", "auth_token_env")].isEnabled()

    view.set_launcher_gate(LauncherProbeResult(False, "fixture failure", stderr="fixture stderr\n"))
    assert view._gate_label.text() == "launcher does not honor config \u2014 install Target B first"
    assert view._details.toPlainText() == "fixture failure\nfixture stderr\n"
    # Other fields still save and the model table is never gated.
    assert view._save_only_btn.isEnabled() and view._table.isEnabled()
    assert view._fields[("server", "auth_token_env")].isEnabled()

    view.set_launcher_gate(LauncherProbeResult(True))
    assert view._gate_label.text() == "launcher honors config \u2014 host/port editable"
    assert view._fields[("server", "port")].isEnabled()
    assert changed == saves == []


def test_pending_gate_refuses_only_host_port_saves(qtbot, five_app_workspace):
    view, _, saves, _, _ = make_view(qtbot, five_app_workspace)
    view._emit_save(False)
    assert [args[2] for args in saves] == [False]
    saves.clear()
    view._fields[("server", "port")].edit.setText("8123")
    view._emit_save(True)
    assert saves == []
    assert (
        view._notice_label.text()
        == "Launcher has not passed the configuration probe; host/port changes cannot be saved."
    )
    # Reverting the listener edit clears the bypass notice and restores saving.
    view._fields[("server", "port")].edit.setText("8000")
    view._emit_save(True)
    assert view._notice_label.text() == ""
    assert [args[2] for args in saves] == [True]
    saves.clear()
    view._fields[("server", "auth_token_env")].present.setChecked(False)
    view._emit_save(True)
    assert [args[2] for args in saves] == [True]


def test_save_in_progress_disables_configuration_but_not_logs(qtbot, five_app_workspace):
    view, _, saves, _, restarts = make_view(qtbot, five_app_workspace)
    view.set_save_in_progress(True)
    assert view._notice_label.text() == "Saving configuration\u2026"
    assert not view._form.isEnabled()
    assert not view._save_only_btn.isEnabled() and not view._save_restart_btn.isEnabled()
    assert view._tabs.isEnabled() and view._restart_btn.isEnabled()
    view._emit_save(False)
    assert saves == []
    view.set_save_in_progress(False)
    assert view._notice_label.text() == ""
    assert view._form.isEnabled() and view._save_only_btn.isEnabled()
    view._restart_btn.click()
    assert restarts == [("chat2api",)]


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("non-writable", "Configuration is not writable; editing is disabled."),
        (
            "yaml-anchors-aliases",
            "YAML anchors or aliases are present; editing is disabled to preserve linked values.",
        ),
    ],
)
def test_read_only_reasons_disable_save_and_explain_why(
    qtbot, five_app_workspace, reason, message
):
    path = bridge_path(five_app_workspace)
    if reason == "non-writable":
        os.chmod(path, 0o444)
    else:
        path.write_text(
            "save_root: &root \"../storage\"\nmax_text_bytes: 1\nport: 8964\ncopy: *root\n",
            encoding="utf-8",
        )
    doc = load("file-bridge", path)
    assert doc.read_only_reasons == (reason,)
    view = StructuredConfigView(get_managed_apps(five_app_workspace)["file-bridge"])
    qtbot.addWidget(view)
    changes, saves = [], []
    view.config_changed.connect(lambda *args: changes.append(args))
    view.save_requested.connect(lambda *args: saves.append(args))
    view.load_config(doc)
    assert not view._form.isEnabled()
    assert not view._save_only_btn.isEnabled() and not view._save_restart_btn.isEnabled()
    assert not view._review_btn.isEnabled()
    assert view._readonly_label.text() == message
    assert view._readonly_label.textFormat() == Qt.TextFormat.PlainText
    view._save_only_btn.click()
    assert changes == saves == []


def test_symlink_load_is_rejected_and_reported(qtbot, five_app_workspace):
    from ai_manager.config.config_errors import SymlinkConfigError

    meta = get_managed_apps(five_app_workspace)["chat2api"]
    path = meta.relative_path / meta.config_file_name
    actual = path.read_bytes()
    path.unlink()
    path.symlink_to(meta.relative_path / meta.example_config_file_name)
    with pytest.raises(SymlinkConfigError) as error:
        load("chat2api", path)
    view = StructuredConfigView(meta)
    qtbot.addWidget(view)
    changes = []
    view.config_changed.connect(lambda *args: changes.append(args))
    view.show_load_error(str(error.value), error.value.reason)
    # The error already names the symlink, so it is not repeated.
    assert view._readonly_label.text() == str(error.value)
    assert "Configuration path is a symlink; editing is disabled." in view._readonly_label.text()
    assert not view._save_only_btn.isEnabled()
    assert not view._form.isEnabled()
    # Header, restart and logs survive a failed load.
    assert view._restart_btn.isEnabled() and view._tabs.isEnabled()
    assert changes == []
    assert (meta.relative_path / meta.example_config_file_name).read_bytes() == actual


def test_non_dict_root_load_error_keeps_no_writable_form(qtbot, five_app_workspace):
    from ai_manager.config.config_errors import ConfigShapeError

    path = bridge_path(five_app_workspace)
    path.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(ConfigShapeError) as error:
        load("file-bridge", path)
    view = StructuredConfigView(get_managed_apps(five_app_workspace)["file-bridge"])
    qtbot.addWidget(view)
    view.show_load_error(error.value.detail, error.value.reason)
    assert view._readonly_label.text() == (
        "Configuration root must be a mapping; save is disabled."
    )
    assert not view._save_only_btn.isEnabled() and not view._form.isEnabled()


def test_missing_config_offers_explicit_creation_only(qtbot, five_app_workspace):
    meta = get_managed_apps(five_app_workspace)["chat2api"]
    path = meta.relative_path / meta.config_file_name
    path.unlink()
    view = StructuredConfigView(meta)
    qtbot.addWidget(view)
    changes, saves = [], []
    view.config_changed.connect(lambda *args: changes.append(args))
    view.save_requested.connect(lambda *args: saves.append(args))
    view.load_config(load("chat2api", path))
    assert view._readonly_label.text() == (
        "Configuration file is missing. Choose Create from Example to start a draft."
    )
    assert not view._save_only_btn.isEnabled()
    assert view._create_btn.isVisibleTo(view)
    view._create_btn.click()
    assert not path.exists()
    assert len(changes) == 1
    assert view.get_current_draft().create_requested
    assert view._save_only_btn.isEnabled()
    assert not view._create_btn.isVisibleTo(view)
    assert saves == []


def test_missing_example_reports_the_exact_path_without_writing(qtbot, five_app_workspace):
    meta = get_managed_apps(five_app_workspace)["file-bridge"]
    (meta.relative_path / meta.config_file_name).unlink()
    (meta.relative_path / meta.example_config_file_name).unlink()
    view = StructuredConfigView(meta)
    qtbot.addWidget(view)
    view.load_config(load("file-bridge", meta.relative_path / meta.config_file_name))
    view._create_btn.click()
    assert view._notice_label.text() == (
        f"Cannot create draft from example: {meta.relative_path / meta.example_config_file_name}"
    )
    assert not (meta.relative_path / meta.config_file_name).exists()


def test_config_error_details_are_plain_text_and_preserve_the_draft(qtbot, five_app_workspace):
    view, _, _, _, _ = make_view(qtbot, five_app_workspace)
    view.set_launcher_gate(LauncherProbeResult(True))
    view._fields[("server", "port")].edit.setText("8123")
    draft = view.get_current_draft()
    stderr = "<tag>synthetic & literal stderr</tag>\nsecond line"
    view.show_config_error(
        "Service validator rejected the configuration; nothing was saved.", stderr
    )
    assert view._notice_label.text() == (
        "Service validator rejected the configuration; nothing was saved."
    )
    assert view._notice_label.textFormat() == Qt.TextFormat.PlainText
    assert view._details.toPlainText() == stderr
    assert view._details.isReadOnly()
    assert view.get_current_draft() == draft
    view.set_validation_result(
        ValidationResult("manager-only", "validated by ai-manager only \u2014 service validator unavailable", "hint")
    )
    assert view._validation_label.text() == (
        "validated by ai-manager only \u2014 service validator unavailable"
    )
    assert view._details.toPlainText() == "hint"


def test_auth_warnings_are_plain_labels(qtbot, five_app_workspace):
    view, _, _, _, _ = make_view(qtbot, five_app_workspace)
    warning = "textkit uses $CHAT2API_TOKEN, but chat2api auth_token_env is <b>None</b>; requests may fail with HTTP 401."
    view.show_auth_warnings((warning, "second warning"))
    assert view._auth_label.text() == f"{warning}\nsecond warning"
    assert view._auth_label.textFormat() == Qt.TextFormat.PlainText


def test_status_updates_log_path_and_badge_without_config_signals(qtbot, five_app_workspace):
    view, changed, saves, fetches, _ = make_view(qtbot, five_app_workspace)
    view.update_service_status(
        ServiceStatus(
            service_id="chat2api",
            state=ServiceRunState.RUNNING,
            pid=104,
            log_path="/tmp/fixture.log",
        )
    )
    assert str(view.log_view._reader.path) == "/tmp/fixture.log"
    view.update_service_status(
        ServiceStatus(service_id="chat2api", state=ServiceRunState.STOPPED)
    )
    # A later report without a path keeps the last known path.
    assert str(view.log_view._reader.path) == "/tmp/fixture.log"
    assert changed == saves == fetches == []


def test_adopt_saved_baseline_without_preserve_reloads_widgets(qtbot, five_app_workspace):
    view, changed, _, _, _ = make_view(qtbot, five_app_workspace)
    view.set_launcher_gate(LauncherProbeResult(True))
    view._fields[("server", "port")].edit.setText("8123")
    committed = load(
        "chat2api", get_managed_apps(five_app_workspace)["chat2api"].relative_path / "config.json"
    )
    view.adopt_saved_baseline(committed, preserve_draft=False)
    assert view._fields[("server", "port")].edit.text() == "8000"
    assert effective_mutations(view.get_current_draft()) == ()
    assert len(changed) == 1


def test_adopt_saved_baseline_preserve_keeps_widget_values_and_rebases(qtbot, five_app_workspace):
    view, changed, _, _, _ = make_view(qtbot, five_app_workspace)
    view.set_launcher_gate(LauncherProbeResult(True))
    view._fields[("server", "port")].edit.setText("8123")
    committed = load(
        "chat2api", get_managed_apps(five_app_workspace)["chat2api"].relative_path / "config.json"
    )
    view.adopt_saved_baseline(committed, preserve_draft=True)
    assert view._fields[("server", "port")].edit.text() == "8123"
    assert effective_mutations(view.get_current_draft()) == (_set(("server", "port"), 8123),)
    assert len(changed) == 1


def test_unknown_kind_raises_and_llm_metadata_is_refused(qtbot, five_app_workspace):
    meta = get_managed_apps(five_app_workspace)["ai-grammar"]
    with pytest.raises(UnknownConfigKindError):
        StructuredConfigView(meta)
    assert "llm" in str(UnknownConfigKindError("llm"))


def test_review_changes_never_writes_the_file(qtbot, five_app_workspace):
    view, _, _, _, _ = make_view(qtbot, five_app_workspace)
    path = get_managed_apps(five_app_workspace)["chat2api"].relative_path / "config.json"
    original = path.read_bytes()
    view.set_launcher_gate(LauncherProbeResult(True))
    view._fields[("server", "port")].edit.setText("8123")
    draft = view.get_current_draft()
    diff = view._baseline.raw_bytes
    assert diff == original
    assert '"port": 8123' in render("chat2api", draft).decode()
    assert path.read_bytes() == original


def test_user_supplied_text_is_never_rich_text(qtbot, five_app_workspace):
    view, _, _, _, _ = make_view(qtbot, five_app_workspace)
    markup = "<b>A & B</b>"
    view.show_auth_warnings((markup,))
    view.show_config_error(markup, markup + "\n")
    view.show_load_error(markup, "load-error")
    for label in (
        view._title_label,
        view._validation_label,
        view._readonly_label,
        view._gate_label,
        view._auth_label,
        view._notice_label,
    ):
        assert label.textFormat() == Qt.TextFormat.PlainText
    for label in view.findChildren(QLabel):
        if label.text() == markup:
            assert label.textFormat() == Qt.TextFormat.PlainText
    details = view.findChildren(QPlainTextEdit)
    assert all(detail.isReadOnly() for detail in details)
    assert markup + "\n" in [detail.toPlainText() for detail in details]


def test_file_bridge_rejects_a_chat2api_document(qtbot, five_app_workspace):
    from ai_manager.config.config_errors import ConfigError

    view, _, _, _, _ = make_view(qtbot, five_app_workspace, "file-bridge")
    chat = load(
        "chat2api",
        get_managed_apps(five_app_workspace)["chat2api"].relative_path / "config.json",
    )
    with pytest.raises(ConfigError):
        view.load_config(chat)


def test_failed_gate_blocks_listener_saves_but_not_other_fields(qtbot, five_app_workspace):
    view, _, saves, _, _ = make_view(qtbot, five_app_workspace)
    view.set_launcher_gate(
        LauncherProbeResult(False, "fixture failure", stderr="fixture stderr\n")
    )
    view._fields[("server", "port")].edit.setText("8123")
    view._emit_save(True)
    assert saves == []
    assert (
        view._notice_label.text()
        == "Launcher has not passed the configuration probe; host/port changes cannot be saved."
    )
    # A failure notice is plain text: native stderr is never rich text.
    assert "<" not in view._gate_label.text()
    view._fields[("server", "port")].edit.setText("8000")
    view._emit_save(True)
    assert [args[2] for args in saves] == [True]


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("load-error", "Cannot load configuration; save is disabled."),
        ("non-dict-root", "Configuration root must be a mapping; save is disabled."),
        ("symlink", "Configuration path is a symlink; editing is disabled."),
    ],
)
def test_load_error_explains_each_reason_and_disables_save(
    qtbot, five_app_workspace, reason, message
):
    view = StructuredConfigView(get_managed_apps(five_app_workspace)["chat2api"])
    qtbot.addWidget(view)
    view.show_load_error("Cannot load configuration /tmp/x: synthetic", reason)
    assert message in view._readonly_label.text().splitlines()
    assert not view._save_only_btn.isEnabled()
    assert not view._save_restart_btn.isEnabled()
    assert not view._form.isEnabled()
    # Logs, restart and the status header stay usable after a failed load.
    assert view._tabs.isEnabled() and view._restart_btn.isEnabled()
    with pytest.raises(ConfigError):
        view.get_current_draft()


def test_reason_text_keeps_every_reason_in_order():
    from ai_manager.ui.structured_config_view import _reason_text

    assert _reason_text(()) == ""
    assert _reason_text(("non-writable", "yaml-anchors-aliases")).splitlines() == [
        "Configuration is not writable; editing is disabled.",
        "YAML anchors or aliases are present; editing is disabled to preserve linked values.",
    ]
    # Duplicates collapse but the first position is retained.
    assert _reason_text(("non-writable", "non-writable")).splitlines() == [
        "Configuration is not writable; editing is disabled."
    ]


def test_renaming_an_expanded_row_keeps_options_and_issues_addressable(
    qtbot, five_app_workspace
):
    path = get_managed_apps(five_app_workspace)["chat2api"].relative_path / "config.json"
    data = json.loads(path.read_bytes())
    data["models"]["echo-1"]["options"] = {"prefix": "hi"}
    path.write_text(json.dumps(data), encoding="utf-8")
    view, _, _, _, _ = make_view(qtbot, five_app_workspace)
    row_id = view._model.rows[0].id
    view._expand_model(row_id)
    assert ("models", "echo-1", "options", "prefix") in view._option_fields
    view._table.item(0, 0).setText("renamed-echo")
    assert set(view._option_fields) == {("models", "renamed-echo", "options", "prefix")}
    assert not any(
        key[0] == "models" and key[1] == "echo-1" for key in view._row_issue_widgets
    )
    tree = json.loads(render("chat2api", view.get_current_draft()))
    assert list(tree["models"]) == ["renamed-echo"]
    assert tree["models"]["renamed-echo"]["options"] == {"prefix": "hi"}
    # Editing the retained field still reaches the renamed route.
    view._option_fields[("models", "renamed-echo", "options", "prefix")].edit.setText("bye")
    tree = json.loads(render("chat2api", view.get_current_draft()))
    assert tree["models"]["renamed-echo"]["options"] == {"prefix": "bye"}


def test_log_view_binds_the_service_id_not_the_display_name(qtbot, five_app_workspace):
    meta = get_managed_apps(five_app_workspace)["chat2api"].model_copy(
        update={"display_name": "Chat & Co"}
    )
    view = StructuredConfigView(meta)
    qtbot.addWidget(view)
    assert view.log_view.service_id == "chat2api"
    view.update_service_status(
        ServiceStatus(service_id="chat2api", state=ServiceRunState.STOPPED)
    )
    assert str(view.log_view._reader.path) == str(default_log_path("chat2api"))
    assert view._title_label.text() == "Chat & Co (Port 8000)"


def test_bypass_notice_clears_as_soon_as_the_listener_edit_is_undone(
    qtbot, five_app_workspace
):
    view, _, saves, _, _ = make_view(qtbot, five_app_workspace)
    view._fields[("server", "port")].edit.setText("8123")
    view._emit_save(False)
    assert saves == []
    assert "Launcher has not passed" in view._notice_label.text()
    # The notice is transient: reverting the edit clears it without a save.
    view._fields[("server", "port")].edit.setText("8000")
    assert view._notice_label.text() == ""
    # A non-listener edit never produces the bypass notice either.
    view._fields[("server", "auth_token_env")].present.setChecked(False)
    assert "Launcher has not passed" not in view._notice_label.text()


def test_create_from_example_survives_an_unexpected_failure(qtbot, tmp_path):
    """A button handler must never let an exception escape the Qt slot.

    An escaping exception from a slot terminated the process (SIGABRT) rather than
    showing an error, and the configuration files are user-supplied.
    """
    from ai_manager.config.models import AppMetadata
    from ai_manager.ui import structured_config_view as scv

    meta = AppMetadata(
        id="chat2api",
        display_name="chat2api",
        relative_path=tmp_path,
        config_file_name="config.json",
        example_config_file_name="config.example.json",
        default_port=8000,
        config_kind="chat2api",
    )
    (tmp_path / "config.example.json").write_text("{}\n", encoding="utf-8")

    view = scv.StructuredConfigView(meta)
    qtbot.addWidget(view)

    errors: list[str] = []
    view.show_config_error = lambda message, detail="": errors.append(message)

    def boom(*_args, **_kwargs):
        raise RecursionError("simulated pathological document")

    original = scv.load_example
    scv.load_example = boom
    try:
        # Must not raise: this is what a real button click does.
        view._create_from_example()
    finally:
        scv.load_example = original

    assert errors, "the failure must be reported to the user"
    assert "example" in errors[0].lower()



# ------------------------------------------------- crash-resistance of slots


@pytest.fixture
def chat2api_view(qtbot, tmp_path):
    """A loaded chat2api view over a throw-away config."""
    from ai_manager.config.models import AppMetadata
    from ai_manager.config.structured_config import load

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {"server": {"port": 8000}, "models": {"e": {"provider": "echo"}}}
        ),
        encoding="utf-8",
    )
    meta = AppMetadata(
        id="chat2api",
        display_name="chat2api",
        relative_path=tmp_path,
        config_file_name="config.json",
        example_config_file_name="config.example.json",
        default_port=8000,
        config_kind="chat2api",
    )
    view = StructuredConfigView(meta)
    qtbot.addWidget(view)
    view.load_config(load("chat2api", config))
    return view


def test_pasting_a_huge_integer_does_not_abort_the_process(qtbot, chat2api_view):
    """5000 digits match the integer pattern but exceed CPython's digit limit.

    ``int()`` then raises ValueError inside a ``textChanged`` slot; an escaping
    exception terminates the application instead of reporting a field error.
    """
    control = chat2api_view._fields[("server", "port")]

    control.edit.setText("9" * 5000)

    # The text is kept verbatim so validation can report it; it must not crash.
    assert control.edit.text() == "9" * 5000
    assert isinstance(control._parse(control.edit.text()), str)


def test_pasting_deeply_nested_raw_options_does_not_abort(qtbot, chat2api_view):
    """``json`` recurses, so a few hundred nested brackets raise RecursionError.

    That happens in a ``textChanged`` slot, and only ``ConfigError`` was caught.
    """
    row_id = chat2api_view._model.rows[0].id
    deep = "[" * 500 + "]" * 500

    chat2api_view._on_raw_options_changed(row_id, '{"future":' + deep + "}")

    # Still a working editable draft; the pathological paste changes no value.
    assert chat2api_view.get_current_draft() is not None


def test_ordinary_raw_options_still_apply(qtbot, chat2api_view):
    row_id = chat2api_view._model.rows[0].id

    chat2api_view._on_raw_options_changed(row_id, '{"future": [[1, 2]]}')

    draft = chat2api_view.get_current_draft()
    assert draft is not None
