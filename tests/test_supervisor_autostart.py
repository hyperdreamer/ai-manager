"""Behavioural tests for the one-shot supervisor autostart attempt.

Every test drives the public entry point (`start_if_not_running`) plus the real
completion callback (`_on_status_finished` / `_on_status_error`). Negative-path
tests arm through the `arm()` helper, which asserts that the attempt was really
claimed and that a probe was really requested, so a no-op implementation cannot
pass them.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QProcess

from ai_manager.services.supervisor import SupervisorManager
from tests.helpers import FakeStatusProcess

SAMPLE_RUNNING_OUTPUT = """[2026-10-04 11:47:44] supervisor running: 34491
ai-grammar   running  pid=2333046 log=/home/henry/.cache/ai-backends/logs/ai-grammar.log
textkit      running  pid=2336549 log=/home/henry/.cache/ai-backends/logs/textkit.log
"""

SAMPLE_STOPPED_OUTPUT = """[2026-10-04 11:47:44] supervisor not running
ai-grammar   stopped  pid=- log=/home/henry/.cache/ai-backends/logs/ai-grammar.log
textkit      stopped  pid=- log=/home/henry/.cache/ai-backends/logs/textkit.log
"""

UNRECOGNISED_OUTPUT = "usage: ai-backends [start|status|stop|restart <name>|kill <name>]\n"


class Recorder:
    """Collects spawned argv plus kwargs, and can be told to raise instead."""

    def __init__(self, raise_oserror: bool = False) -> None:
        self.argv: list[list[str]] = []
        self.kwargs: list[dict] = []
        self.raise_oserror = raise_oserror

    def __call__(self, argv, **kwargs):
        self.argv.append(list(argv))
        self.kwargs.append(dict(kwargs))
        if self.raise_oserror:
            raise OSError("nope")
        return MagicMock()


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr("ai_manager.services.supervisor.subprocess.Popen", rec)
    return rec


@pytest.fixture
def manager(qtbot, tmp_path, autostart_enabled, recorder):
    m = SupervisorManager(workspace_root=tmp_path)
    m._status_process = FakeStatusProcess()
    return m


def fresh_manager(tmp_path, monkeypatch):
    """A manager plus a reset of the process-wide claim.

    Needed by tests that build two managers: the real code keeps the claim
    process-wide, so a previous test's claim would otherwise leak in.
    """
    monkeypatch.setattr(SupervisorManager, "_autostart_consumed", False)
    monkeypatch.setattr(SupervisorManager, "_autostart_cancel_epoch", 0)
    case = SupervisorManager(workspace_root=tmp_path)
    case._status_process = FakeStatusProcess()
    return case


def deliver(manager, output, code=0, status=QProcess.ExitStatus.NormalExit):
    """Complete the in-flight probe with the given output and exit details."""
    manager._status_process.finish()
    manager._status_output_buffer.clear()
    manager._status_output_buffer.extend(output.encode("utf-8"))
    manager._on_status_finished(code, status)


def arm(manager):
    """Claim the attempt and prove a probe was really launched.

    Counts from the current baseline so a test that deliberately provoked an
    earlier (non-claiming) poll can still arm.
    """
    before = len(manager._status_process.starts)
    assert manager.start_if_not_running() is True
    assert len(manager._status_process.starts) == before + 1
    assert manager.claim_is_live() is True


def test_starts_once_when_status_reports_stopped(manager, recorder):
    arm(manager)
    deliver(manager, SAMPLE_STOPPED_OUTPUT)

    assert recorder.argv == [[manager.executable, "start"]]
    assert recorder.kwargs[0]["start_new_session"] is True


def test_does_not_start_when_running(manager, recorder):
    arm(manager)
    deliver(manager, SAMPLE_RUNNING_OUTPUT)

    assert recorder.argv == []


def test_is_one_shot_across_repeated_entry_calls(manager, recorder):
    arm(manager)
    assert manager.start_if_not_running() is False
    deliver(manager, SAMPLE_STOPPED_OUTPUT)
    assert len(recorder.argv) == 1

    # The successful start must have requested a follow-up probe; complete it so
    # the busy guard cannot mask a missing one-shot guard.
    assert len(manager._status_process.starts) == 2, "follow-up probe was not requested"
    assert manager._status_process.state() == QProcess.ProcessState.Running
    deliver(manager, SAMPLE_RUNNING_OUTPUT)
    assert manager._status_process.state() == QProcess.ProcessState.NotRunning
    starts_before = len(manager._status_process.starts)

    assert manager.start_if_not_running() is False
    assert len(manager._status_process.starts) == starts_before

    deliver(manager, SAMPLE_STOPPED_OUTPUT)
    assert len(recorder.argv) == 1


def test_manual_stop_during_first_probe_never_converts_into_a_start(manager, recorder):
    arm(manager)
    manager.stop_supervisor()
    deliver(manager, SAMPLE_STOPPED_OUTPUT)

    assert recorder.argv == [[manager.executable, "stop"]]


def test_manual_start_during_first_probe_never_double_starts(manager, recorder):
    arm(manager)
    manager.start_supervisor()
    deliver(manager, SAMPLE_STOPPED_OUTPUT)

    starts = [a for a in recorder.argv if a[1] == "start"]
    assert len(starts) == 1


def test_probe_failure_does_not_start_and_a_later_status_cannot_rearm(manager, recorder):
    arm(manager)
    manager._on_status_error(QProcess.ProcessError.FailedToStart)
    deliver(manager, SAMPLE_STOPPED_OUTPUT)

    assert recorder.argv == []


def test_unrecognised_output_never_starts(tmp_path, autostart_enabled, monkeypatch):
    for output in ("", UNRECOGNISED_OUTPUT, SAMPLE_RUNNING_OUTPUT + SAMPLE_STOPPED_OUTPUT):
        monkeypatch.setattr(SupervisorManager, "_autostart_consumed", False)
        monkeypatch.setattr(SupervisorManager, "_autostart_cancel_epoch", 0)
        case_recorder = Recorder()
        monkeypatch.setattr(
            "ai_manager.services.supervisor.subprocess.Popen", case_recorder
        )
        case = SupervisorManager(workspace_root=tmp_path)
        case._status_process = FakeStatusProcess()

        arm(case)
        deliver(case, output)

        assert case_recorder.argv == [], f"output={output!r}"


def test_nonzero_exit_never_starts(manager, recorder):
    arm(manager)
    deliver(manager, SAMPLE_STOPPED_OUTPUT, code=3)

    assert recorder.argv == []


def test_abnormal_exit_status_never_starts(manager, recorder):
    arm(manager)
    deliver(manager, SAMPLE_STOPPED_OUTPUT, status=QProcess.ExitStatus.CrashExit)

    assert recorder.argv == []


def test_disabled_by_environment(qtbot, tmp_path, recorder, monkeypatch):
    from ai_manager.services.supervisor import AUTOSTART_DISABLE_ENV

    for value in ("1", "true", "TRUE", " yes "):
        monkeypatch.setattr(SupervisorManager, "_autostart_consumed", False)
        case = SupervisorManager(workspace_root=tmp_path)
        case._status_process = FakeStatusProcess()
        monkeypatch.setenv(AUTOSTART_DISABLE_ENV, value)

        assert case.start_if_not_running() is False
        assert case._status_process.starts == []
        assert SupervisorManager._autostart_consumed is False

    # Positive control: the same state, with the variable removed, must start.
    monkeypatch.delenv(AUTOSTART_DISABLE_ENV, raising=False)
    recorded = Recorder()
    monkeypatch.setattr("ai_manager.services.supervisor.subprocess.Popen", recorded)
    case = SupervisorManager(workspace_root=tmp_path)
    case._status_process = FakeStatusProcess()

    arm(case)
    deliver(case, SAMPLE_STOPPED_OUTPUT)
    assert recorded.argv == [[case.executable, "start"]]


def test_second_manager_never_starts_again(tmp_path, recorder, monkeypatch, autostart_enabled):
    a = fresh_manager(tmp_path, monkeypatch)
    b = fresh_manager(tmp_path, monkeypatch)

    arm(a)
    assert b.start_if_not_running() is False

    deliver(a, SAMPLE_STOPPED_OUTPUT)
    assert len(recorder.argv) == 1

    deliver(b, SAMPLE_STOPPED_OUTPUT)
    assert len(recorder.argv) == 1


def test_automatic_spawn_failure_is_silent(manager, recorder):
    collected = []
    manager.action_completed.connect(lambda *args: collected.append(args))
    recorder.raise_oserror = True

    arm(manager)
    deliver(manager, SAMPLE_STOPPED_OUTPUT)

    assert len(recorder.argv) == 1, "the spawn must actually be attempted"
    assert collected == []


def test_manual_spawn_failure_still_reports(manager, recorder):
    collected = []
    manager.action_completed.connect(lambda *args: collected.append(args))
    recorder.raise_oserror = True

    manager.start_supervisor()

    assert collected == [
        ("start_supervisor", False, "Failed to start supervisor: nope")
    ]


def test_followup_probe_requested_only_after_a_successful_automatic_start(
    qtbot, tmp_path, autostart_enabled, recorder, monkeypatch
):
    def run_case(deliveries, fail_spawn=False):
        monkeypatch.setattr(SupervisorManager, "_autostart_consumed", False)
        monkeypatch.setattr(SupervisorManager, "_autostart_cancel_epoch", 0)
        case_recorder = Recorder(raise_oserror=fail_spawn)
        monkeypatch.setattr("ai_manager.services.supervisor.subprocess.Popen", case_recorder)
        case = SupervisorManager(workspace_root=tmp_path)
        case._status_process = FakeStatusProcess()

        requests = []
        real_refresh = case.refresh_status
        monkeypatch.setattr(
            case, "refresh_status", lambda: requests.append(True) or real_refresh()
        )
        arm(case)
        for output in deliveries:
            deliver(case, output)
        # Let the fake settle so the next sub-case starts from a clean probe state.
        case._status_process.finish()
        SupervisorManager._autostart_cancel_epoch += 1
        return len(requests)

    assert run_case([SAMPLE_STOPPED_OUTPUT]) == 2        # initial + follow-up
    assert run_case([SAMPLE_STOPPED_OUTPUT], fail_spawn=True) == 1
    assert run_case([SAMPLE_RUNNING_OUTPUT]) == 1


def test_cancel_is_process_wide_across_managers(tmp_path, recorder, monkeypatch, autostart_enabled):
    a = fresh_manager(tmp_path, monkeypatch)
    b = fresh_manager(tmp_path, monkeypatch)

    arm(a)
    b.stop_supervisor()
    deliver(a, SAMPLE_STOPPED_OUTPUT)

    assert recorder.argv == [[b.executable, "stop"]]


def test_busy_probe_is_not_claimed(tmp_path, autostart_enabled, recorder, monkeypatch):
    case = fresh_manager(tmp_path, monkeypatch)
    case._status_process.start(case.executable, ["status"])  # a poll is in flight

    assert case.start_if_not_running() is False
    assert SupervisorManager._autostart_consumed is False

    case._status_process.finish()
    arm(case)  # positive control: a free probe does arm


def test_only_the_claiming_manager_may_complete_the_claim(tmp_path, recorder, monkeypatch, autostart_enabled):
    a = fresh_manager(tmp_path, monkeypatch)
    b = fresh_manager(tmp_path, monkeypatch)

    # B takes an ordinary status poll first (not an autostart entry).
    b.refresh_status()
    assert b._autostart_epoch is None

    arm(a)
    deliver(b, SAMPLE_STOPPED_OUTPUT)
    assert recorder.argv == []
    assert a.claim_is_live() is True

    deliver(a, SAMPLE_STOPPED_OUTPUT)
    assert recorder.argv == [[a.executable, "start"]]


def test_another_managers_poll_cannot_consume_or_authorise_the_claim(
    tmp_path, recorder, monkeypatch, autostart_enabled
):
    a = fresh_manager(tmp_path, monkeypatch)
    b = fresh_manager(tmp_path, monkeypatch)

    # B's ordinary poll is in flight and stays there while A claims.
    b.refresh_status()
    arm(a)

    deliver(b, SAMPLE_STOPPED_OUTPUT)
    assert recorder.argv == []

    deliver(a, SAMPLE_STOPPED_OUTPUT)
    assert recorder.argv == [[a.executable, "start"]]


def test_status_receiver_that_stops_wins(manager, recorder):
    manager.status_updated.connect(lambda _status: manager.stop_supervisor())

    arm(manager)
    deliver(manager, SAMPLE_STOPPED_OUTPUT)

    assert recorder.argv == [[manager.executable, "stop"]]


def test_reentrant_status_receiver_cannot_double_start(manager, recorder):
    fired = {"once": False}

    def reentrant(_status):
        if fired["once"]:
            return
        fired["once"] = True
        # A receiver that synchronously requests another probe and completes it.
        manager.refresh_status()
        deliver(manager, SAMPLE_STOPPED_OUTPUT)

    manager.status_updated.connect(reentrant)

    arm(manager)
    deliver(manager, SAMPLE_STOPPED_OUTPUT)

    starts = [a for a in recorder.argv if a[1] == "start"]
    assert len(starts) == 1, f"re-entrant receiver caused {len(starts)} starts"
    # The outer callback's follow-up probe is still in flight; completing it as
    # running must not produce a second start either.
    assert manager._status_process.state() == QProcess.ProcessState.Running
    deliver(manager, SAMPLE_RUNNING_OUTPUT)
    assert len([a for a in recorder.argv if a[1] == "start"]) == 1
