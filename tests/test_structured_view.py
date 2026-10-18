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
