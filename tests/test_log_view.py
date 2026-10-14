"""Qt tests for the bounded live service log view.

The view consumes the reader's bounded ``LogReadBatch`` objects and renders
untrusted log text as plain text only.  Reader behaviour is exercised through
the required ``view._reader`` seam so these tests never touch the filesystem.
"""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QPlainTextEdit,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ai_manager.config.models import ServiceRunState
from ai_manager.services.log_tailer import (
    FilePresence,
    LogFileStatus,
    LogReadBatch,
)
from ai_manager.ui.widgets.log_view import LogViewWidget


class StubReader:
    """Replaceable reader seam recording calls and replaying queued batches."""

    def __init__(self):
        self.path = None
        self.presence = (FilePresence.UNSET, None)
        self.batches = deque()
        self.set_path_calls = []
        self.probe_calls = 0
        self.read_calls = 0

    def set_path(self, path):
        normalized = None if path is None else Path(os.fspath(path))
        changed = normalized != self.path
        self.path = normalized
        self.set_path_calls.append(normalized)
        return changed

    def probe_health(self):
        self.probe_calls += 1
        return self.presence

    def read_new_lines(self):
        self.read_calls += 1
        if self.batches:
            return self.batches.popleft()
        if self.path is None:
            # Match the real reader: no target means status UNSET, not OK.
            return LogReadBatch([], status=LogFileStatus.UNSET)
        return LogReadBatch([])


def make_view(qtbot):
    """Construct a widget with the reader seam installed and registered."""
    view = LogViewWidget("svc")
    qtbot.addWidget(view)
    stub = StubReader()
    view._reader = stub
    return view, stub


def _lines(view):
    return view.logView.toPlainText().splitlines()


# ---------------------------------------------------------------------------
# Rendering, cap and pause/follow semantics
# ---------------------------------------------------------------------------


def test_poll_once_appends_plain_text_and_updates_counter(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path(Path("/tmp/service.log"))

    stub.batches.append(LogReadBatch(["<b>untrusted</b>", "& raw"]))
    view.poll_once()

    assert view.logView.objectName() == "logView"
    assert view.logView.isReadOnly()
    assert view.logView.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap
    assert view.logView.toPlainText() == "<b>untrusted</b>\n& raw"
    assert _lines(view) == ["<b>untrusted</b>", "& raw"]
    assert view._line_counter.objectName() == "logLineCounter"
    assert view._line_counter.text() == "2 lines"


def test_line_counter_ignores_health_placeholder(qtbot):
    view, stub = make_view(qtbot)
    stub.batches.append(LogReadBatch([f"line {i}" for i in range(3)]))
    view.poll_once()

    assert "No log file resolved yet" in view.logView.toPlainText()
    assert view._line_counter.text() == "3 lines"


def test_maximum_block_count_caps_display(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("cap.log")

    total = LogViewWidget.MAX_LINES + 5
    stub.batches.append(LogReadBatch([f"line {i}" for i in range(total)]))
    view.poll_once()

    assert view.logView.maximumBlockCount() == LogViewWidget.MAX_LINES
    assert view.logView.document().blockCount() <= LogViewWidget.MAX_LINES
    assert view._line_counter.text().endswith("lines (capped)")
    assert "line 0" not in view.logView.toPlainText()
    assert f"line {total - 1}" in view.logView.toPlainText()


def test_evicted_placeholder_collision_does_not_delete_real_log_line(qtbot):
    view, stub = make_view(qtbot)
    missing_placeholder = "Log file not found: missing.log"
    stub.presence = (FilePresence.MISSING, missing_placeholder)
    view.set_log_path("missing.log")
    view.poll_once()
    assert _lines(view).count(missing_placeholder) == 1

    stub.presence = (FilePresence.PRESENT, None)
    real_lines = [missing_placeholder] + [
        f"real line {index}" for index in range(LogViewWidget.MAX_LINES - 1)
    ]
    stub.batches.append(LogReadBatch(real_lines, status=LogFileStatus.OK))
    view.poll_once()

    assert view.logView.document().blockCount() == LogViewWidget.MAX_LINES
    assert _lines(view)[0] == missing_placeholder
    assert _lines(view).count(missing_placeholder) == 1
    assert view._health_chip.text() == "● Live"


def test_pause_prevents_consumption_and_resume_drains(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("pause.log")

    view.set_paused(True)
    assert "Resume" in view._pause_button.text()
    stub.batches.append(LogReadBatch(["while paused"]))
    view.poll_once()
    view.poll_once()

    assert stub.probe_calls == 2
    assert stub.read_calls == 0
    assert "while paused" not in view.logView.toPlainText()

    view.set_paused(False)
    assert "Pause" in view._pause_button.text()
    view.poll_once()

    assert stub.read_calls == 1
    assert "while paused" in view.logView.toPlainText()


def test_follow_controls_only_viewport(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("follow.log")
    view.resize(400, 150)
    view.show()
    qtbot.waitExposed(view)

    stub.batches.append(LogReadBatch([f"line {i}" for i in range(200)]))
    view.poll_once()
    bar = view.logView.verticalScrollBar()
    assert bar.maximum() > 0
    assert bar.value() == bar.maximum()

    view.set_follow(False)
    assert view._follow_check.isChecked() is False
    bar.setValue(0)
    stub.batches.append(LogReadBatch([f"later {i}" for i in range(50)]))
    view.poll_once()

    # An unchecked Follow never yanks the viewport to the bottom.
    assert bar.value() == 0
    assert "later 0" in view.logView.toPlainText()

    view.set_follow(True)
    assert view._follow_check.isChecked() is True
    stub.batches.append(LogReadBatch(["final line"]))
    view.poll_once()
    qtbot.wait(20)

    assert bar.value() == bar.maximum()
    assert view.logView.textCursor().atEnd()
    assert view.logView.document().blockCount() == 251
    assert "final line" in view.logView.toPlainText()
    assert "line 0" in view.logView.toPlainText()


def test_clear_view_does_not_reset_reader(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("clear.log")
    stub.batches.append(LogReadBatch(["first output"]))
    view.poll_once()
    assert stub.read_calls == 1
    assert stub.path == Path("clear.log")

    view.clear_view()

    assert view.logView.toPlainText() == ""
    assert stub.path == Path("clear.log")
    assert stub.read_calls == 1
    view.poll_once()
    assert "first output" not in view.logView.toPlainText()

    stub.batches.append(LogReadBatch(["second output"]))
    view.poll_once()
    assert "second output" in view.logView.toPlainText()
    assert "first output" not in view.logView.toPlainText()


# ---------------------------------------------------------------------------
# Marker lines and path changes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reset", "marker"),
    [
        ("created", "------ log file created ------"),
        ("truncated", "------ log truncated ------"),
        ("rotated", "------ log rotated ------"),
    ],
)
def test_reset_markers_are_exact_and_precede_lines(qtbot, reset, marker):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("a.log")

    stub.batches.append(LogReadBatch(["after reset"], reset=reset))
    view.poll_once()

    lines = _lines(view)
    assert marker in lines
    assert lines.index(marker) < lines.index("after reset")

    view.set_log_path("b.log")
    stub.batches.append(LogReadBatch(["new target"]))
    view.poll_once()

    lines = _lines(view)
    changed = "------ log file changed: b.log ------"
    assert lines.index(changed) < lines.index("new target")
    assert "after reset" in lines


def test_path_changes_preserve_history_and_isolate_offsets(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("a.log")
    stub.batches.append(LogReadBatch(["alpha output"]))
    view.poll_once()
    assert "alpha output" in view.logView.toPlainText()

    view.set_log_path("b.log")
    stub.batches.append(LogReadBatch(["bravo output"]))
    view.poll_once()

    text = view.logView.toPlainText()
    marker = "------ log file changed: b.log ------"
    assert "alpha output" in text
    assert "bravo output" in text
    assert text.count(marker) == 1
    lines = text.splitlines()
    assert lines.index(marker) < lines.index("bravo output")

    # A repeated report of the same path adds no marker and keeps history.
    view.set_log_path("b.log")
    stub.batches.append(LogReadBatch(["charlie output"]))
    view.poll_once()

    text = view.logView.toPlainText()
    assert text.count(marker) == 1
    assert "bravo output" in text
    assert "charlie output" in text
    assert text.count("alpha output") == 1
    assert stub.set_path_calls == [Path("a.log"), Path("b.log")]


# ---------------------------------------------------------------------------
# File-health chip and single-placeholder bookkeeping
# ---------------------------------------------------------------------------


def test_health_placeholders_are_single_and_transition_only(qtbot):
    view, stub = make_view(qtbot)

    missing = "Log file not found: /tmp/svc.log"
    stub.presence = (FilePresence.MISSING, missing)
    view.poll_once()
    assert view._health_chip.objectName() == "logStatusChip"
    assert view._health_chip.text() == "⚠ Log file not found"
    view.poll_once()
    assert _lines(view).count(missing) == 1

    unavailable = "Cannot read log file: [Errno 13] Permission denied"
    stub.presence = (FilePresence.UNAVAILABLE, unavailable)
    view.poll_once()
    text = view.logView.toPlainText()
    assert text.count(missing) == 0
    assert text.count(unavailable) == 1
    assert view._health_chip.text() == "⚠ Log unreadable: [Errno 13] Permission denied"

    # Repeated read-observed unreadable batches do not stack placeholders.
    stub.presence = (FilePresence.PRESENT, None)
    unreadable = LogReadBatch(
        [], status=LogFileStatus.UNREADABLE, error="permission denied"
    )
    stub.batches.append(unreadable)
    stub.batches.append(unreadable)
    view.poll_once()
    assert view._health_chip.text() == "⚠ Log unreadable: permission denied"
    view.poll_once()
    assert view.logView.toPlainText().count("Cannot read log file: permission denied") == 1

    # An OK-derived state removes the placeholder.
    stub.batches.append(LogReadBatch([], status=LogFileStatus.OK))
    view.poll_once()
    assert view._health_chip.text() == "● Live"
    assert "Cannot read log file" not in view.logView.toPlainText()


def test_missing_file_is_observed_while_paused(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("paused-missing.log")
    view.set_paused(True)

    missing = "Log file not found: paused-missing.log"
    stub.presence = (FilePresence.MISSING, missing)
    view.poll_once()
    assert view._health_chip.text() == "⚠ Log file not found"
    assert missing in view.logView.toPlainText()
    assert stub.read_calls == 0

    stub.presence = (FilePresence.PRESENT, None)
    view.poll_once()
    assert view._health_chip.text() == "⏸ Paused"
    assert stub.read_calls == 0
    assert view.logView.toPlainText() == ""

    stub.batches.append(LogReadBatch(["content after resume"]))
    view.poll_once()
    assert stub.read_calls == 0
    assert "content after resume" not in view.logView.toPlainText()

    view.set_paused(False)
    view.poll_once()
    assert stub.read_calls == 1
    assert "content after resume" in view.logView.toPlainText()


def test_read_error_survives_paused_present_probe(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("unreadable.log")
    stub.batches.append(
        LogReadBatch([], status=LogFileStatus.UNREADABLE, error="permission denied")
    )
    view.poll_once()
    assert view._health_chip.text() == "⚠ Log unreadable: permission denied"
    assert "Cannot read log file: permission denied" in view.logView.toPlainText()

    view.set_paused(True)
    stub.presence = (FilePresence.PRESENT, None)
    view.poll_once()
    assert view._health_chip.text() == "⚠ Log unreadable: permission denied"
    assert "Cannot read log file: permission denied" in view.logView.toPlainText()

    view.set_paused(False)
    stub.batches.append(LogReadBatch([], status=LogFileStatus.OK))
    view.poll_once()
    assert view._health_chip.text() == "● Live"
    assert "Cannot read log file" not in view.logView.toPlainText()
    assert "log file created" not in view.logView.toPlainText()


def test_clearing_resolved_path_resets_hidden_view_to_unset(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("resolved.log")
    stub.batches.append(LogReadBatch(["last real line"]))
    view.poll_once()
    assert view._health_chip.text() == "● Live"
    assert "last real line" in view.logView.toPlainText()
    assert view.is_polling is False
    calls_before = (stub.probe_calls, stub.read_calls)

    view.set_log_path(None)

    assert view._target_path is None
    assert view._health_chip.text() == "◌ No log path"
    assert "No log file resolved yet" in view.logView.toPlainText()
    assert "last real line" in view.logView.toPlainText()
    assert (stub.probe_calls, stub.read_calls) == calls_before


def test_read_observed_missing_while_paused_shows_paused(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("race.log")

    # A read observes ENOENT after the PRESENT probe (the target was deleted or
    # replaced between the stat and the open).
    missing = "Log file not found: race.log"
    stub.batches.append(
        LogReadBatch([], status=LogFileStatus.MISSING, error=missing)
    )
    view.poll_once()
    assert view._health_chip.text() == "⚠ Log file not found"
    assert missing in view.logView.toPlainText()

    # `PRESENT | paused | anything other than UNREADABLE` is the `⏸ Paused`
    # row, and the stale read-observed placeholder must not survive.
    view.set_paused(True)
    assert view._health_chip.text() == "⏸ Paused"
    assert stub.read_calls == 1
    assert "Log file not found" not in view.logView.toPlainText()


def test_resume_before_first_read_never_shows_live(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("resume-first.log")

    view.set_paused(True)
    view.poll_once()  # probe PRESENT, but a paused tick consumes nothing
    assert stub.read_calls == 0
    assert view._health_chip.text() == "⏸ Paused"

    # A stat-only PRESENT probe cannot promote the chip to Live: no read of the
    # current path has succeeded yet.
    view.set_paused(False)
    assert view._health_chip.text() != "● Live"
    assert stub.read_calls == 0

    stub.batches.append(LogReadBatch([], status=LogFileStatus.OK))
    view.poll_once()
    assert view._health_chip.text() == "● Live"
    assert stub.read_calls == 1


def test_visible_resume_reads_immediately(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("visible-resume.log")
    view.show()
    qtbot.waitExposed(view)
    assert view.is_polling is True

    view.set_paused(True)
    view.poll_once()
    reads_while_paused = stub.read_calls

    # While the widget is polling, Resume probes and reads synchronously so the
    # chip never waits for the one-second timer.
    view.set_paused(False)
    assert stub.read_calls == reads_while_paused + 1
    assert view._health_chip.text() == "● Live"


def test_visible_path_change_reads_immediately(qtbot):
    view, stub = make_view(qtbot)
    view.show()
    qtbot.waitExposed(view)
    assert view.is_polling is True

    probes_before = stub.probe_calls
    reads_before = stub.read_calls
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("switched.log")

    # A path switch while actively polling refreshes the chip synchronously so
    # the displayed state can never describe the previous path.
    assert stub.probe_calls == probes_before + 1
    assert stub.read_calls == reads_before + 1
    assert view._health_chip.text() == "● Live"


def test_service_state_and_file_health_are_independent(qtbot):
    view, stub = make_view(qtbot)
    expected = {
        ServiceRunState.RUNNING: "service running",
        ServiceRunState.STOPPED: "service stopped",
        ServiceRunState.TRANSITIONING: "service restarting",
        ServiceRunState.UNKNOWN: "service unknown",
    }
    for state, text in expected.items():
        view.set_service_state(state)
        assert view._service_state_label.text() == text
        assert view._service_state_label.objectName() == "logServiceState"

    view.set_service_state(ServiceRunState.RUNNING)
    missing = "Log file not found: x.log"
    stub.presence = (FilePresence.MISSING, missing)
    view.poll_once()
    assert view._health_chip.text() == "⚠ Log file not found"

    # A service-state update cannot clear a file-health warning.
    view.set_service_state(ServiceRunState.STOPPED)
    assert view._service_state_label.text() == "service stopped"
    assert view._health_chip.text() == "⚠ Log file not found"
    assert missing in view.logView.toPlainText()

    view.set_service_state(ServiceRunState.RUNNING)
    stub.presence = (FilePresence.PRESENT, None)
    stub.batches.append(
        LogReadBatch([], status=LogFileStatus.UNREADABLE, error="permission denied")
    )
    view.poll_once()
    assert view._health_chip.text() == "⚠ Log unreadable: permission denied"
    assert view._service_state_label.text() == "service running"


# ---------------------------------------------------------------------------
# Toolbar controls
# ---------------------------------------------------------------------------


def test_open_copy_and_clear_controls(qtbot, monkeypatch, tmp_path):
    view, stub = make_view(qtbot)

    assert isinstance(view._pause_button, QToolButton)
    assert isinstance(view._follow_check, QCheckBox)
    assert view._follow_check.isChecked() is True
    assert not view._open_button.isEnabled()
    assert not view._copy_button.isEnabled()
    assert "no log file" in view._open_button.toolTip().lower()
    assert "no log file" in view._copy_button.toolTip().lower()

    log_path = tmp_path / "svc.log"
    view.set_log_path(log_path)
    assert view._open_button.isEnabled()
    assert view._copy_button.isEnabled()

    opened = []

    def fake_from_local(path):
        opened.append(("file", path))
        return QUrl("file:///fake")

    def fake_open_url(url):
        opened.append(("open", url.toString()))
        return True

    monkeypatch.setattr(QUrl, "fromLocalFile", staticmethod(fake_from_local))
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(fake_open_url))
    view._open_button.click()
    assert opened == [("file", str(log_path)), ("open", "file:///fake")]

    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: False))
    view._open_button.click()
    assert view._health_chip.toolTip() == str(log_path)

    stub.presence = (FilePresence.PRESENT, None)
    stub.batches.append(LogReadBatch(["first line", "second line"]))
    view.poll_once()
    assert view.logView.toPlainText() == "first line\nsecond line"

    cursor = view.logView.textCursor()
    cursor.clearSelection()
    view.logView.setTextCursor(cursor)
    view._copy_button.click()
    assert QApplication.clipboard().text() == "first line\nsecond line"

    cursor = view.logView.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(len("first line"), QTextCursor.MoveMode.KeepAnchor)
    view.logView.setTextCursor(cursor)
    view._copy_button.click()
    assert QApplication.clipboard().text() == "first line"

    view._clear_button.click()
    assert view.logView.toPlainText() == ""
    assert stub.read_calls == 1
    assert stub.path == log_path


# ---------------------------------------------------------------------------
# Read budget and visibility gating
# ---------------------------------------------------------------------------


def test_poll_once_never_exceeds_read_budget(qtbot):
    view, stub = make_view(qtbot)
    stub.presence = (FilePresence.PRESENT, None)
    view.set_log_path("budget.log")
    for i in range(6):
        stub.batches.append(LogReadBatch([f"batch {i}"], more_pending=True))

    view.poll_once()

    assert stub.probe_calls == 1
    assert stub.read_calls == LogViewWidget.MAX_READS_PER_TICK
    assert "batch 0" in view.logView.toPlainText()
    assert "batch 3" in view.logView.toPlainText()
    assert "batch 4" not in view.logView.toPlainText()
    assert len(stub.batches) == 2

    # The next tick continues draining instead of dropping pending data.
    view.poll_once()

    assert stub.probe_calls == 2
    assert stub.read_calls == 7
    assert "batch 4" in view.logView.toPlainText()
    assert "batch 5" in view.logView.toPlainText()


def test_visibility_gates_timer_in_real_qt_containers(qtbot):
    view = LogViewWidget("svc")
    qtbot.addWidget(view)
    view._reader = StubReader()

    tabs = QTabWidget()
    tabs.addTab(QWidget(), "Configuration")
    tabs.addTab(view, "Logs")
    qtbot.addWidget(tabs)
    tabs.resize(400, 300)
    tabs.show()
    qtbot.waitExposed(tabs)

    assert view.is_polling is False
    tabs.setCurrentIndex(1)
    assert view.is_polling is True
    tabs.setCurrentIndex(0)
    assert view.is_polling is False

    stacked_view = LogViewWidget("svc2")
    qtbot.addWidget(stacked_view)
    stacked_view._reader = StubReader()
    stack = QStackedWidget()
    page0 = QWidget()
    page1 = QWidget()
    stack.addWidget(page0)
    stack.addWidget(page1)
    layout = QVBoxLayout(page1)
    layout.addWidget(stacked_view)
    qtbot.addWidget(stack)
    stack.resize(400, 300)
    stack.show()
    qtbot.waitExposed(stack)

    assert stacked_view.is_polling is False
    stack.setCurrentIndex(1)
    assert stacked_view.is_polling is True
    stack.setCurrentIndex(0)
    assert stacked_view.is_polling is False
