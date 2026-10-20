from pathlib import Path
from unittest.mock import MagicMock

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
