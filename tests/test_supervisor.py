from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QByteArray, QObject, QProcess

from ai_manager.config.models import ServiceRunState
from ai_manager.services.supervisor import SupervisorManager, parse_supervisor_status

SAMPLE_RUNNING_OUTPUT = """[2026-10-04 11:47:44] supervisor running: 34491
ai-grammar   running  pid=2333046 log=/home/henry/.cache/ai-backends/logs/ai-grammar.log
textkit      running  pid=2336549 log=/home/henry/.cache/ai-backends/logs/textkit.log
yt2txt       stopped  pid=- log=/home/henry/.cache/ai-backends/logs/yt2txt.log
chat2api     running  pid=42974 log=/home/henry/.cache/ai-backends/logs/chat2api.log
"""

SAMPLE_STOPPED_OUTPUT = """[2026-10-04 11:47:44] supervisor not running
ai-grammar   stopped  pid=- log=/home/henry/.cache/ai-backends/logs/ai-grammar.log
textkit      stopped  pid=- log=/home/henry/.cache/ai-backends/logs/textkit.log
"""


def test_parse_supervisor_running():
    status = parse_supervisor_status(SAMPLE_RUNNING_OUTPUT)
    assert status.is_running is True
    assert status.supervisor_pid == 34491
    assert len(status.services) == 4

    grammar = status.services["ai-grammar"]
    assert grammar.state == ServiceRunState.RUNNING
    assert grammar.pid == 2333046
    assert grammar.log_path == "/home/henry/.cache/ai-backends/logs/ai-grammar.log"

    yt = status.services["yt2txt"]
    assert yt.state == ServiceRunState.STOPPED
    assert yt.pid is None


def test_parse_supervisor_stopped():
    status = parse_supervisor_status(SAMPLE_STOPPED_OUTPUT)
    assert status.is_running is False
    assert status.supervisor_pid is None
    assert len(status.services) == 2
    assert status.services["ai-grammar"].state == ServiceRunState.STOPPED


def test_stop_supervisor_runs_stop_command(qtbot, monkeypatch, tmp_path):
    recorded = {}

    def fake_popen(args, **kwargs):
        recorded["args"] = list(args)
        recorded["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr(
        "ai_manager.services.supervisor.subprocess.Popen", fake_popen
    )
    manager = SupervisorManager(workspace_root=tmp_path)
    # Isolate from the real QProcess status probe so only the stop command runs.
    monkeypatch.setattr(
        manager, "refresh_status", lambda: recorded.__setitem__("refreshed", True)
    )

    with qtbot.waitSignal(manager.action_completed, timeout=1000) as blocker:
        manager.stop_supervisor()

    action, success, _msg = blocker.args
    assert action == "stop_supervisor"
    assert success is True
    assert recorded["args"] == [manager.executable, "stop"]
    assert recorded["args"][1:] == ["stop"]
    assert recorded["kwargs"].get("start_new_session") is True
    assert recorded.get("refreshed") is True


def test_default_log_path_uses_cache_logs_directory(monkeypatch, tmp_path):
    from ai_manager.services.supervisor import default_log_path
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    result = default_log_path("textkit")
    assert result == (
        tmp_path / ".cache" / "ai-backends" / "logs" / "textkit.log"
    )
    assert not result.parent.exists()


def test_five_service_status_and_hyphenated_restart(qtbot, tmp_path):
    from PyQt6.QtCore import QProcess

    from ai_manager.services.supervisor import SupervisorManager, parse_supervisor_status

    text = """[2026-10-17 16:07:34] supervisor running: 34491
ai-grammar   running  pid=101 log=/tmp/logs/ai-grammar.log
textkit      running  pid=102 log=/tmp/logs/textkit.log
yt2txt       stopped  pid=- log=/tmp/logs/yt2txt.log
chat2api     running  pid=104 log=/tmp/logs/chat2api.log
file-bridge  running  pid=105 log=/tmp/logs/file-bridge.log
"""
    status = parse_supervisor_status(text)
    assert len(status.services) == 5 and status.services["yt2txt"].pid is None
    assert status.services["file-bridge"].state == ServiceRunState.RUNNING
    assert status.services["file-bridge"].pid == 105
    assert status.services["file-bridge"].log_path == "/tmp/logs/file-bridge.log"
    manager = SupervisorManager(tmp_path)
    manager._action_process = MagicMock()
    manager._action_process.state.return_value = QProcess.ProcessState.NotRunning
    manager.restart_service("file-bridge")
    manager._action_process.start.assert_called_once_with(
        manager.executable, ["restart", "file-bridge"]
    )


class _ActionSignal:
    """Retain retired callbacks so tests can deliver an already queued signal."""

    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)

    def emit(self, *args):
        for callback in tuple(self.callbacks):
            callback(*args)


class ControlledActionProcess(QObject):
    """Only the QProcess surface consumed here; start never executes a command."""

    ProcessState = QProcess.ProcessState
    ProcessError = QProcess.ProcessError
    ExitStatus = QProcess.ExitStatus

    def __init__(self, parent=None):
        super().__init__(parent)
        self.finished = _ActionSignal()
        self.errorOccurred = _ActionSignal()
        self.readyReadStandardOutput = _ActionSignal()
        self._state = self.ProcessState.NotRunning
        self.starts = []
        self.stdout = b""
        self.stderr = b""
        self.error = "missing launcher fixture"

    def state(self):
        return self._state

    def start(self, program, args):
        self.starts.append((program, args))
        self._state = self.ProcessState.Running

    def readAllStandardOutput(self):
        data, self.stdout = self.stdout, b""
        return QByteArray(data)

    def readAllStandardError(self):
        data, self.stderr = self.stderr, b""
        return QByteArray(data)

    def errorString(self):
        return self.error

    def fail_to_start(self):
        self._state = self.ProcessState.NotRunning
        self.errorOccurred.emit(self.ProcessError.FailedToStart)

    def finish(self, code=0):
        self._state = self.ProcessState.NotRunning
        self.finished.emit(code, self.ExitStatus.NormalExit)


@pytest.fixture
def controlled_manager(qtbot, monkeypatch, tmp_path):
    import ai_manager.services.supervisor as supervisor

    monkeypatch.setattr(supervisor, "QProcess", ControlledActionProcess)
    manager = SupervisorManager(tmp_path)
    return manager


def test_failed_to_start_finishes_once_without_finished(controlled_manager):
    manager = controlled_manager
    completed = []
    manager.action_completed.connect(lambda *args: completed.append(args))
    manager.restart_service("ai-grammar")
    manager._action_process.fail_to_start()
    assert completed == [("restart ai-grammar", False, "missing launcher fixture")]
    assert manager._current_action == ""
    manager._action_process.finish(1)
    assert completed == [("restart ai-grammar", False, "missing launcher fixture")]


def test_old_attempt_callback_cannot_finish_new_attempt(controlled_manager):
    manager = controlled_manager
    process = manager._action_process
    completed = []
    manager.action_completed.connect(lambda *args: completed.append(args))
    manager.restart_service("ai-grammar")
    old_finished = process.finished.callbacks[-1]
    old_errors = tuple(process.errorOccurred.callbacks)
    process.finish()
    assert completed == [("restart ai-grammar", True, "Exited with code 0")]
    assert manager._current_action == ""
    manager.restart_service("textkit")
    process.stderr = b"second attempt failed\xff"
    old_finished(1, QProcess.ExitStatus.NormalExit)
    for callback in old_errors:
        callback(QProcess.ProcessError.FailedToStart)
    assert len(completed) == 1
    assert manager._current_action == "restart textkit"
    process.finish(2)
    assert completed == [
        ("restart ai-grammar", True, "Exited with code 0"),
        ("restart textkit", False, "second attempt failed\ufffd"),
    ]
    assert manager._current_action == ""
    assert not process.finished.callbacks and not process.errorOccurred.callbacks


@pytest.mark.parametrize("use_stderr", [True, False])
def test_terminal_clears_active_state_before_reentrant_restart(controlled_manager, use_stderr):
    manager = controlled_manager
    process = manager._action_process
    completed, active_at_terminal = [], []

    def terminal(*args):
        completed.append(args)
        if len(completed) == 1:
            active_at_terminal.append(manager._current_action)
            manager.restart_service("textkit")

    manager.action_completed.connect(terminal)
    manager.restart_service("ai-grammar")
    if use_stderr:
        process.stderr, process.stdout = b" stderr fixture \n", b"ignored stdout"
    else:
        process.stdout = b" stdout fixture \n"
    process.errorOccurred.emit(QProcess.ProcessError.ReadError)
    assert completed == []
    process.finish()
    assert active_at_terminal == [""]
    assert completed == [("restart ai-grammar", True, "stderr fixture" if use_stderr else "stdout fixture")]
    assert manager._current_action == "restart textkit"
    assert len(process.finished.callbacks) == len(process.errorOccurred.callbacks) == 1
    process.fail_to_start()
    assert completed[-1] == ("restart textkit", False, "missing launcher fixture")


def test_busy_restart_is_an_immediate_unqualified_terminal(controlled_manager):
    manager = controlled_manager
    completed = []
    manager.action_completed.connect(lambda *args: completed.append(args))
    manager.restart_service("ai-grammar")
    manager.restart_service("textkit")
    assert completed == [("restart", False, "Another supervisor command is in progress.")]
    assert manager._current_action == "restart ai-grammar"
    assert len(manager._action_process.starts) == 1
    manager._action_process.finish()
    assert completed[-1][0] == "restart ai-grammar"
