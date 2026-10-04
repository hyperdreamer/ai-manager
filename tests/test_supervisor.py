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
