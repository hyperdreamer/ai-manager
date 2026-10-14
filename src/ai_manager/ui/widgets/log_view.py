"""Bounded, read-only live log view for a single supervised service.

The view owns one :class:`LogTailReader` and renders whatever bounded batches
it produces as *plain text*.  Log output is untrusted: it is appended with
``appendPlainText()`` and is never interpreted as HTML or markup.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Tuple, Union

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import (
    QDesktopServices,
    QFontDatabase,
    QTextBlockUserData,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ai_manager.config.models import ServiceRunState
from ai_manager.services.log_tailer import (
    FilePresence,
    LogFileStatus,
    LogReadBatch,
    LogTailReader,
)

_RESET_MARKERS = {
    "created": "------ log file created ------",
    "truncated": "------ log truncated ------",
    "rotated": "------ log rotated ------",
}

_READ_ERROR_PREFIX = "Cannot read log file: "
_MISSING_PREFIX = "Log file not found: "

_NO_LOG_PATH_CHIP = "\u25cc No log path"
_MISSING_CHIP = "\u26a0 Log file not found"
_UNREADABLE_CHIP = "\u26a0 Log unreadable: {}"
_PAUSED_CHIP = "\u23f8 Paused"
_LIVE_CHIP = "\u25cf Live"

_NO_PATH_PLACEHOLDER = "No log file resolved yet"
_NO_PATH_TOOLTIP = "No log file resolved yet"

_SERVICE_STATE_TEXT = {
    ServiceRunState.RUNNING: "service running",
    ServiceRunState.STOPPED: "service stopped",
    ServiceRunState.TRANSITIONING: "service restarting",
    ServiceRunState.UNKNOWN: "service unknown",
}


def _unreadable_texts(message: Optional[str]) -> Tuple[str, str]:
    """Return ``(chip reason, placeholder)`` for an unreadable message.

    The reader reports complete user-facing messages (``Cannot read log file:
    <reason>``) while batches may carry a bare reason; both forms are accepted
    without duplicating the prefix.
    """
    if message is None:
        reason = "unknown error"
    elif message.startswith(_READ_ERROR_PREFIX):
        reason = message[len(_READ_ERROR_PREFIX):]
    else:
        reason = message
    return reason, f"{_READ_ERROR_PREFIX}{reason}"


class _PlaceholderBlockData(QTextBlockUserData):
    """Identity tag preventing a recycled cursor from matching log text."""

    def __init__(self, token: int) -> None:
        super().__init__()
        self.token = token


class LogViewWidget(QWidget):
    """Live log page for one service; polls a bounded incremental reader."""

    LOG_POLL_INTERVAL_MS = 1000
    MAX_LINES = 5000
    MAX_READS_PER_TICK = 4

    def __init__(self, service_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service_id = service_id
        self._reader = LogTailReader(
            initial_bytes=65536,
            max_batch_bytes=262144,
            max_line_bytes=16384,
        )
        self._target_path: Optional[Path] = None
        self._paused = False
        self._follow = True
        self._presence: FilePresence = FilePresence.UNSET
        self._presence_reason: Optional[str] = None
        self._last_read_status: LogFileStatus = LogFileStatus.UNSET
        self._last_read_error: Optional[str] = None
        self._health_key: Optional[Tuple[str, Optional[str]]] = None
        self._placeholder_cursor = None
        self._placeholder_text: Optional[str] = None
        self._placeholder_token = 0
        self._pending_path_marker: Optional[str] = None

        self._build_ui()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.LOG_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self.poll_once)

        self._update_file_controls()
        self._refresh_health()
        self._update_line_counter()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def service_id(self) -> str:
        """The id of the service this view renders logs for (read-only)."""
        return self._service_id

    def set_log_path(self, path: Optional[Union[str, Path]]) -> None:
        """Point the reader at a new target, preserving displayed history."""
        normalized = None if path is None else Path(os.fspath(path))
        if normalized == self._target_path:
            # A repeated report of the same path keeps history and adds no
            # marker; the reader's own change detection is left untouched.
            return
        previous = self._target_path
        self._target_path = normalized
        self._reader.set_path(normalized)
        self._last_read_status = LogFileStatus.UNSET
        self._last_read_error = None
        if normalized is None:
            self._presence = FilePresence.UNSET
            self._presence_reason = None
            self._health_key = None
        has_history = previous is not None
        if normalized is not None and has_history:
            self._pending_path_marker = (
                f"------ log file changed: {normalized} ------"
            )
        else:
            self._pending_path_marker = None
        self._update_file_controls()
        self._refresh_immediately()

    def set_service_state(self, state: ServiceRunState) -> None:
        """Update only the muted service-state line."""
        self._service_state_label.setText(
            _SERVICE_STATE_TEXT.get(state, "service unknown")
        )

    def set_paused(self, paused: bool) -> None:
        """Gate content consumption; presence is still probed every tick.

        Resuming refreshes health immediately (including an immediate read
        while the widget is polling), so the chip never waits for the next
        timer tick to leave the paused state.
        """
        self._paused = bool(paused)
        self._pause_button.setText("▶ Resume" if self._paused else "⏸ Pause")
        self._refresh_immediately()

    def set_follow(self, follow: bool) -> None:
        """Control auto-scroll only."""
        self._follow = bool(follow)
        if self._follow_check.isChecked() != self._follow:
            self._follow_check.blockSignals(True)
            self._follow_check.setChecked(self._follow)
            self._follow_check.blockSignals(False)

    def clear_view(self) -> None:
        """Wipe displayed text only; reader state is untouched."""
        self.logView.clear()
        self._placeholder_cursor = None
        self._placeholder_text = None
        self._placeholder_token = 0
        self._update_line_counter()

    def poll_once(self) -> None:
        """One poll tick: probe presence, consume bounded batches, refresh UI."""
        presence, reason = self._reader.probe_health()
        self._presence = presence
        self._presence_reason = reason

        if not self._paused:
            reads = 0
            while reads < self.MAX_READS_PER_TICK:
                batch = self._reader.read_new_lines()
                reads += 1
                self._last_read_status = batch.status
                self._last_read_error = batch.error
                if batch.status == LogFileStatus.OK:
                    if self._pending_path_marker is not None:
                        self._append_line(self._pending_path_marker)
                        self._pending_path_marker = None
                    marker = _RESET_MARKERS.get(batch.reset)
                    if marker is not None:
                        self._append_line(marker)
                for line in batch.lines:
                    self._append_line(line)
                if not batch.more_pending:
                    break

        self._refresh_health()
        self._update_line_counter()

    @property
    def is_polling(self) -> bool:
        return self._poll_timer.isActive()

    # ------------------------------------------------------------------
    # Qt lifecycle
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().showEvent(event)
        self._poll_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._poll_timer.stop()
        super().hideEvent(event)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self._health_chip = QLabel(_NO_LOG_PATH_CHIP, self)
        self._health_chip.setObjectName("logStatusChip")
        toolbar.addWidget(self._health_chip)

        self._pause_button = QToolButton(self)
        self._pause_button.setObjectName("logPauseButton")
        self._pause_button.setText("⏸ Pause")
        self._pause_button.clicked.connect(self._on_pause_clicked)
        toolbar.addWidget(self._pause_button)

        self._follow_check = QCheckBox("Follow", self)
        self._follow_check.setObjectName("logFollowCheck")
        self._follow_check.setChecked(True)
        self._follow_check.toggled.connect(self._on_follow_toggled)
        toolbar.addWidget(self._follow_check)

        toolbar.addStretch(1)

        self._open_button = QToolButton(self)
        self._open_button.setObjectName("logOpenButton")
        self._open_button.setText("Open log file")
        self._open_button.clicked.connect(self._on_open_clicked)
        toolbar.addWidget(self._open_button)

        self._copy_button = QToolButton(self)
        self._copy_button.setObjectName("logCopyButton")
        self._copy_button.setText("Copy")
        self._copy_button.clicked.connect(self._on_copy_clicked)
        toolbar.addWidget(self._copy_button)

        self._clear_button = QToolButton(self)
        self._clear_button.setObjectName("logClearButton")
        self._clear_button.setText("Clear")
        self._clear_button.clicked.connect(self._on_clear_clicked)
        toolbar.addWidget(self._clear_button)

        root.addLayout(toolbar)

        self.logView = QPlainTextEdit(self)
        self.logView.setObjectName("logView")
        self.logView.setReadOnly(True)
        self.logView.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.logView.setMaximumBlockCount(self.MAX_LINES)
        self.logView.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        root.addWidget(self.logView, 1)

        status = QHBoxLayout()
        self._service_state_label = QLabel(
            _SERVICE_STATE_TEXT[ServiceRunState.UNKNOWN], self
        )
        self._service_state_label.setObjectName("logServiceState")
        status.addWidget(self._service_state_label)
        status.addStretch(1)
        self._line_counter = QLabel("0 lines", self)
        self._line_counter.setObjectName("logLineCounter")
        status.addWidget(self._line_counter)
        root.addLayout(status)

    # ------------------------------------------------------------------
    # Health derivation and placeholder bookkeeping
    # ------------------------------------------------------------------

    def _refresh_immediately(self) -> None:
        """Refresh health now, polling when the widget is actively polling.

        A hidden page performs no log syscalls (visibility contract), so it
        only re-derives the chip from retained state; the first visible tick
        polls.  A polling widget probes and reads synchronously so transitions
        such as Resume or a path switch never wait on the timer.
        """
        if not self._paused and self._poll_timer.isActive():
            self.poll_once()
        else:
            self._refresh_health()

    def _derive_health(self) -> Optional[Tuple[str, str, Optional[str]]]:
        """Return ``(category, chip text, placeholder)`` from current state.

        ``None`` means the chip is retained: presence is ``PRESENT`` but no
        read has succeeded for the current path yet, and a stat-only probe
        must never promote the chip to Live by itself.
        """
        if self._presence == FilePresence.UNSET:
            return "unset", _NO_LOG_PATH_CHIP, _NO_PATH_PLACEHOLDER
        if self._presence == FilePresence.MISSING:
            return "missing", _MISSING_CHIP, self._missing_placeholder(
                self._presence_reason
            )
        if self._presence == FilePresence.UNAVAILABLE:
            reason, placeholder = _unreadable_texts(self._presence_reason)
            return "unreadable", _UNREADABLE_CHIP.format(reason), placeholder

        # PRESENT.  Only a read-observed UNREADABLE may outrank the pause
        # dimension; every other retained status yields the paused row while
        # paused.  A MISSING read observation still outranks OK (it must never
        # show Live), and a never-read path retains the current chip.
        if self._last_read_status == LogFileStatus.UNREADABLE:
            reason, placeholder = _unreadable_texts(self._last_read_error)
            return "unreadable", _UNREADABLE_CHIP.format(reason), placeholder
        if self._paused:
            return "paused", _PAUSED_CHIP, None
        if self._last_read_status == LogFileStatus.MISSING:
            return "missing", _MISSING_CHIP, self._missing_placeholder(
                self._last_read_error
            )
        if self._last_read_status == LogFileStatus.OK:
            return "live", _LIVE_CHIP, None
        return None

    def _missing_placeholder(self, message: Optional[str]) -> str:
        if message is not None and message.startswith(_MISSING_PREFIX):
            return message
        path = self._target_path
        if path is None:
            path = self._reader.path
        if message is not None:
            return f"{_MISSING_PREFIX}{message}"
        if path is not None:
            return f"{_MISSING_PREFIX}{path}"
        return _NO_PATH_PLACEHOLDER

    def _refresh_health(self) -> None:
        derived = self._derive_health()
        if derived is None:
            # No successful read of the current path yet: retain the current
            # chip rather than promoting a stat-only PRESENT probe to Live.
            return
        category, chip, placeholder = derived
        self._health_chip.setText(chip)
        key = (category, placeholder)
        if key == self._health_key:
            # Errors are surfaced once per transition, not once per poll.
            return
        self._health_key = key
        # A replacement can temporarily shrink the scroll range; preserve the
        # viewport across the whole transition as well as each text mutation.
        with self._preserve_viewport():
            self._remove_placeholder()
            if placeholder is not None:
                self._append_placeholder(placeholder)

    def _append_placeholder(self, text: str) -> None:
        self._append_line(text)
        # Hold a live cursor (not a bare block handle): maximumBlockCount
        # trimming recycles stale QTextBlock handles onto other blocks.
        block = self.logView.document().lastBlock()
        self._placeholder_token += 1
        block.setUserData(_PlaceholderBlockData(self._placeholder_token))
        self._placeholder_cursor = QTextCursor(block)
        self._placeholder_text = text

    def _remove_placeholder(self) -> None:
        cursor = self._placeholder_cursor
        text = self._placeholder_text
        token = self._placeholder_token
        self._placeholder_cursor = None
        self._placeholder_text = None
        if cursor is None or text is None:
            return
        block = cursor.block()
        data = block.userData() if block.isValid() else None
        if (
            not block.isValid()
            or block.text() != text
            or not isinstance(data, _PlaceholderBlockData)
            or data.token != token
        ):
            # The placeholder was already trimmed away; never touch real lines.
            return
        with self._preserve_viewport():
            removal = QTextCursor(block)
            removal.movePosition(
                QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor
            )
            if removal.hasSelection():
                removal.removeSelectedText()
            else:
                removal.select(QTextCursor.SelectionType.BlockUnderCursor)
                removal.removeSelectedText()

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _preserve_viewport(self) -> Iterator[None]:
        """Prevent Qt's implicit scrolling during mutations with Follow off."""
        if self._follow:
            yield
            return
        vertical = self.logView.verticalScrollBar()
        horizontal = self.logView.horizontalScrollBar()
        position = (vertical.value(), horizontal.value())
        try:
            yield
        finally:
            vertical.setValue(position[0])
            horizontal.setValue(position[1])

    def _append_line(self, text: str) -> None:
        with self._preserve_viewport():
            self.logView.appendPlainText(text)
            if self._follow:
                self.logView.moveCursor(QTextCursor.MoveOperation.End)

    def _placeholder_is_displayed(self) -> bool:
        if self._placeholder_cursor is None or self._placeholder_text is None:
            return False
        block = self._placeholder_cursor.block()
        data = block.userData() if block.isValid() else None
        return (
            block.isValid()
            and block.text() == self._placeholder_text
            and isinstance(data, _PlaceholderBlockData)
            and data.token == self._placeholder_token
        )

    def _update_line_counter(self) -> None:
        document = self.logView.document()
        count = 0 if document.isEmpty() else document.blockCount()
        if self._placeholder_is_displayed() and count > 0:
            # The placeholder is a status line, not log output.
            count -= 1
        if document.blockCount() >= self.MAX_LINES:
            self._line_counter.setText(f"{count} lines (capped)")
        else:
            self._line_counter.setText(f"{count} lines")

    def _update_file_controls(self) -> None:
        resolved = self._target_path is not None
        tooltip = "" if resolved else _NO_PATH_TOOLTIP
        for button in (self._open_button, self._copy_button):
            button.setEnabled(resolved)
            button.setToolTip(tooltip)

    # ------------------------------------------------------------------
    # Control handlers
    # ------------------------------------------------------------------

    def _on_pause_clicked(self) -> None:
        self.set_paused(not self._paused)

    def _on_follow_toggled(self, checked: bool) -> None:
        self._follow = bool(checked)

    def _on_open_clicked(self) -> None:
        path = self._target_path
        if path is None:
            return
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self._health_chip.setToolTip("")
        else:
            # Keep the failure actionable in headless or desktop environments.
            self._health_chip.setToolTip(str(path))

    def _on_copy_clicked(self) -> None:
        cursor = self.logView.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText().replace("\u2029", "\n")
        else:
            text = self.logView.toPlainText()
        QApplication.clipboard().setText(text)

    def _on_clear_clicked(self) -> None:
        self.clear_view()
