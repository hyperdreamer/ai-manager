"""Read-only dialogs for change review, blast radius, staleness and reports.

None of these dialogs writes files. ``ReviewChangesDialog`` renders a local
unified diff, ``BlastRadiusDialog`` returns the explicitly checked app ids,
``StaleDocumentDialog`` returns one of three choice tokens, and
``TransactionReportDialog`` reports a failed transaction without attempting
recovery itself.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ai_manager.config.structured_models import DependentMatch, TransactionReport
from ai_manager.ui.mnemonic import escape_mnemonic


def _label(text, parent):
    """Create a word-wrapped plain-text ``QLabel`` (never rich text)."""
    label = QLabel(parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(text)
    label.setWordWrap(True)
    return label


class ReviewChangesDialog(QDialog):
    """Show the saved-to-draft unified diff without writing anything."""

    def __init__(self, before: bytes, after: bytes, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Changes")
        self.resize(850, 550)
        layout = QVBoxLayout(self)
        layout.addWidget(_label(str(path), self))
        detail = QPlainTextEdit(self)
        detail.setReadOnly(True)
        before_text = before.decode("utf-8", errors="replace").splitlines(keepends=True)
        after_text = after.decode("utf-8", errors="replace").splitlines(keepends=True)
        detail.setPlainText(
            "".join(
                difflib.unified_diff(
                    before_text,
                    after_text,
                    fromfile="saved",
                    tofile="draft",
                )
            )
        )
        layout.addWidget(detail)
        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)
        layout.addWidget(close)


class BlastRadiusDialog(QDialog):
    """Ask which dependent apps should receive a rewritten ``ai.api_base``.

    Every checkbox starts unchecked so selection is explicitly opt-in.
    """

    def __init__(self, matches: tuple[DependentMatch, ...], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update dependent API base URLs?")
        self._checks: dict[str, QCheckBox] = {}
        self._primary_only = False
        layout = QVBoxLayout(self)
        if matches:
            old_url, new_url = matches[0].old_api_base, matches[0].new_api_base
            layout.addWidget(
                _label(
                    f"Changing chat2api from {old_url} to {new_url} affects these "
                    "apps. Only checked apps will have ai.api_base updated.",
                    self,
                )
            )
        for match in matches:
            checkbox = QCheckBox(
                escape_mnemonic(
                    f"{match.meta.display_name}: {match.old_api_base} "
                    f"\u2192 {match.new_api_base}"
                ),
                self,
            )
            checkbox.setChecked(False)
            self._checks[match.meta.id] = checkbox
            layout.addWidget(checkbox)
            if match.auth_warning:
                layout.addWidget(_label(match.auth_warning, self))
        actions = QHBoxLayout()
        selected = QPushButton("Save with Selected Updates", self)
        selected.clicked.connect(self.accept)
        alone = QPushButton("Save chat2api Only", self)
        alone.clicked.connect(self._save_alone)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        for button in (selected, alone, cancel):
            actions.addWidget(button)
        layout.addLayout(actions)

    def _save_alone(self):
        self._primary_only = True
        self.accept()

    def selected_app_ids(self) -> tuple[str, ...]:
        if self._primary_only:
            return ()
        return tuple(
            app_id
            for app_id, checkbox in self._checks.items()
            if checkbox.isChecked()
        )


class StaleDocumentDialog(QDialog):
    """Ask what to do when the on-disk document changed under a draft."""

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration Changed")
        self._choice = "cancel"
        layout = QVBoxLayout(self)
        layout.addWidget(_label("Configuration changed on disk; save refused.", self))
        layout.addWidget(_label(str(path), self))
        layout.addWidget(_label("Reload discards this app's unsaved draft.", self))
        actions = QHBoxLayout()
        for text, choice in (
            ("Reload", "reload"),
            ("Show diff", "diff"),
            ("Cancel", "cancel"),
        ):
            button = QPushButton(text, self)
            button.clicked.connect(
                lambda checked=False, value=choice: self._choose(value)
            )
            actions.addWidget(button)
        layout.addLayout(actions)

    def _choose(self, choice):
        self._choice = choice
        self.accept()

    def choice(self):
        return self._choice


class TransactionReportDialog(QDialog):
    """Report a failed configuration transaction phase by phase."""

    def __init__(self, report: TransactionReport, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration Save Failed")
        layout = QVBoxLayout(self)
        if report.restore_failures:
            summary = (
                "Save failed and some files could not be restored. Review every "
                "path below before restarting services."
            )
        else:
            summary = {
                "backups": (
                    "Could not create all backups; no configuration files were "
                    "changed."
                ),
                "stage": (
                    "Could not stage configuration files; no configuration files "
                    "were changed."
                ),
            }.get(
                report.phase,
                "Save failed; configuration files were restored from backups.",
            )
        layout.addWidget(_label(summary, self))
        details = QPlainTextEdit(self)
        details.setReadOnly(True)
        lines = [f"{path}: {state}" for path, state in report.files.items()]
        lines += [f"Backup {path}: {backup}" for path, backup in report.backups.items()]
        lines += [
            f"{path}: {reason}" for path, reason in report.restore_failures.items()
        ]
        if report.error:
            lines.append(report.error)
        if report.restore_failures:
            lines.append(
                "Reload affected files after resolving the reported recovery "
                "failures."
            )
        details.setPlainText("\n".join(lines))
        layout.addWidget(details)
        close = QPushButton("Close", self)
        close.clicked.connect(self.accept)
        layout.addWidget(close)
