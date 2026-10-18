"""Capability-gate tests for chat2api listener editing.

Every launcher in this module is a fake ``start.sh`` created under ``tmp_path``
that only prints text. No real application tree, config, credentials or
listener is touched: the gate's contract is that it *asks* the launcher what it
would serve and never opens, reserves or probes a port itself.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from ai_manager.config.models import AppMetadata
from ai_manager.config.structured_models import LauncherProbeResult
from ai_manager.services import config_jobs, launcher_gate
from ai_manager.services.launcher_gate import probe_launcher

GATE_SOURCE = Path(launcher_gate.__file__).read_text(encoding="utf-8")
JOBS_SOURCE = Path(config_jobs.__file__).read_text(encoding="utf-8")

OK_OUTPUT = 'printf "127.0.0.1\\n8123\\n"\n'


def _write_launcher(directory: Path, body: str, *, mode: int = 0o755) -> Path:
    """Create an executable fake ``start.sh`` in *directory*."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "start.sh"
    script.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    script.chmod(mode)
    return script


def _meta(directory: Path) -> AppMetadata:
    return AppMetadata(
        id="chat2api",
        display_name="chat2api",
        relative_path=directory,
        default_port=8000,
        config_kind="chat2api",
    )


# --------------------------------------------------------------------------- #
# Success shape
# --------------------------------------------------------------------------- #


def test_print_listener_success(tmp_path):
    _write_launcher(tmp_path, OK_OUTPUT)
    result = probe_launcher(tmp_path)
    assert result.passed is True
    assert result.returncode == 0
    assert result.stdout == "127.0.0.1\n8123\n"
    assert result.stderr == ""
    assert "127.0.0.1:8123" in result.detail


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "LOCALHOST", "LocalHost"])
def test_accepts_every_loopback_spelling(tmp_path, host):
    _write_launcher(tmp_path, f'printf "{host}\\n8123\\n"\n')
    result = probe_launcher(tmp_path)
    assert result.passed is True, result.detail
    assert result.returncode == 0


@pytest.mark.parametrize("port", ["1", "8000", "65535"])
def test_accepts_the_full_port_range(tmp_path, port):
    _write_launcher(tmp_path, f'printf "127.0.0.1\\n{port}\\n"\n')
    assert probe_launcher(tmp_path).passed is True


@pytest.mark.parametrize(
    "body",
    [
        'printf "127.0.0.1\\n"\n',
        'printf "127.0.0.1\\n8123\\n8000\\n"\n',
        'printf ""\n',
        'printf "127.0.0.1\\n8123\\nextra diagnostic\\n"\n',
        "true\n",
    ],
)
def test_exactly_two_non_empty_lines_are_required(tmp_path, body):
    _write_launcher(tmp_path, body)
    assert probe_launcher(tmp_path).passed is False, body


def test_blank_lines_around_the_two_values_are_ignored(tmp_path):
    _write_launcher(tmp_path, 'printf "\\n127.0.0.1\\n8123\\n\\n"\n')
    assert probe_launcher(tmp_path).passed is True


# --------------------------------------------------------------------------- #
# Rejections
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",
        "::",
        "127.0.0.2",
        "192.168.1.5",
        "example.com",
        "localhost.",
        "[::1]",
        " 127.0.0.1",
        "127.0.0.1 ",
        "127.0.0.1\t",
        "local host",
    ],
)
def test_rejects_non_loopback_host(tmp_path, host):
    _write_launcher(tmp_path, f'printf "{host}\\n8123\\n"\n')
    result = probe_launcher(tmp_path)
    assert result.passed is False, host
    assert result.returncode == 0  # the launcher itself succeeded; the answer did not


@pytest.mark.parametrize("port", ["0", "65536", "-1", "notanint", "", "8123x", "8 123", " 8123", "8123 ", "8_123", "+8123"])
def test_rejects_out_of_range_or_malformed_port(tmp_path, port):
    _write_launcher(tmp_path, f'printf "127.0.0.1\\n{port}\\n"\n')
    assert probe_launcher(tmp_path).passed is False, port


def test_nonzero_exit_fails_even_with_a_valid_two_line_answer(tmp_path):
    _write_launcher(tmp_path, 'printf "127.0.0.1\\n8123\\n"\necho "partial failure" >&2\nexit 3\n')
    result = probe_launcher(tmp_path)
    assert result.passed is False
    assert result.returncode == 3
    assert "partial failure" in result.detail


def test_legacy_launcher_without_the_flag_fails_closed(tmp_path):
    _write_launcher(tmp_path, 'echo "No such option" >&2\nexit 2\n')
    result = probe_launcher(tmp_path)
    assert result.passed is False
    assert result.returncode == 2
    assert result.detail == "No such option"


def test_rejection_detail_carries_the_captured_stderr(tmp_path):
    _write_launcher(
        tmp_path,
        'printf "0.0.0.0\\n8000\\n"\necho "listener check: non-loopback host" >&2\n',
    )
    result = probe_launcher(tmp_path)
    assert result.passed is False
    assert result.detail == "listener check: non-loopback host"
    assert "0.0.0.0" in result.stdout


def test_rejection_detail_falls_back_to_stdout_when_stderr_is_empty(tmp_path):
    _write_launcher(tmp_path, 'printf "127.0.0.1\\n0\\n"\n')
    result = probe_launcher(tmp_path)
    assert result.passed is False
    assert "127.0.0.1" in result.detail and "0" in result.detail


def test_timeout_is_a_failure(tmp_path):
    # ``exec`` replaces the shell so the timed-out child is the only process:
    # the gate must not use process-group signalling, so nothing else may linger.
    _write_launcher(tmp_path, "exec sleep 30\n")
    started = time.monotonic()
    result = probe_launcher(tmp_path, timeout_s=0.5)
    elapsed = time.monotonic() - started
    assert result.passed is False
    assert "timed out" in result.detail.lower()
    assert elapsed < 10, "the gate must give up at its own deadline"


def test_missing_launcher_is_a_failure(tmp_path):
    result = probe_launcher(tmp_path)
    assert result.passed is False
    assert result.detail == f"No launcher at {tmp_path / 'start.sh'}"
    assert result.returncode is None
    assert result.stdout == "" and result.stderr == ""


def test_missing_launcher_never_spawns_a_process(tmp_path, monkeypatch):
    recorder = _RecordingSubprocess()
    monkeypatch.setattr(launcher_gate, "subprocess", recorder)
    assert probe_launcher(tmp_path).passed is False
    assert recorder.calls == []


# --------------------------------------------------------------------------- #
# Invocation contract
# --------------------------------------------------------------------------- #


def test_launcher_receives_the_flag_and_runs_in_the_app_directory(tmp_path):
    _write_launcher(
        tmp_path,
        'printf "%s\\n" "$@" > invoked-args.txt\n'
        'printf "%s" "$PWD" > invoked-cwd.txt\n'
        'printf "127.0.0.1\\n8123\\n"\n',
    )
    assert probe_launcher(tmp_path).passed is True
    assert (tmp_path / "invoked-args.txt").read_text(encoding="utf-8") == "--print-listener\n"
    assert (tmp_path / "invoked-cwd.txt").read_text(encoding="utf-8") == str(tmp_path)


def test_launcher_inherits_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_MANAGER_GATE_TEST", "inherited")
    _write_launcher(
        tmp_path,
        'printf "%s" "$AI_MANAGER_GATE_TEST" > inherited.txt\n' + OK_OUTPUT,
    )
    assert probe_launcher(tmp_path).passed is True
    assert (tmp_path / "inherited.txt").read_text(encoding="utf-8") == "inherited"


def test_probe_is_uncached(tmp_path):
    _write_launcher(
        tmp_path,
        'n=$(( $(cat calls.txt 2>/dev/null || echo 0) + 1 ))\n'
        'echo "$n" > calls.txt\n'
        'printf "127.0.0.1\\n$((8122 + n))\\n"\n',
    )
    first = probe_launcher(tmp_path)
    second = probe_launcher(tmp_path)
    assert first.passed is True and second.passed is True
    assert "8123" in first.detail
    assert "8124" in second.detail
    assert (tmp_path / "calls.txt").read_text(encoding="utf-8").strip() == "2"


class _RecordingSubprocess:
    """Stand-in for the ``subprocess`` module that records the exact call."""

    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, stdout: str = "127.0.0.1\n8123\n", stderr: str = "", returncode: int = 0):
        self.calls: list[tuple[tuple, dict]] = []
        self._completed = subprocess.CompletedProcess(
            args=["start.sh", "--print-listener"],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._completed


def test_subprocess_invocation_contract(tmp_path, monkeypatch):
    _write_launcher(tmp_path, OK_OUTPUT)
    recorder = _RecordingSubprocess()
    monkeypatch.setattr(launcher_gate, "subprocess", recorder)

    assert probe_launcher(tmp_path, timeout_s=3.5).passed is True

    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]
    assert args == ([str(tmp_path / "start.sh"), "--print-listener"],)
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["timeout"] == 3.5
    assert kwargs.get("env") is None  # inherited environment, never a scrubbed copy


def test_default_timeout_is_ten_seconds(tmp_path, monkeypatch):
    _write_launcher(tmp_path, OK_OUTPUT)
    recorder = _RecordingSubprocess()
    monkeypatch.setattr(launcher_gate, "subprocess", recorder)
    probe_launcher(tmp_path)
    assert recorder.calls[0][1]["timeout"] == 10.0


def test_non_executable_launcher_is_a_failure(tmp_path):
    _write_launcher(tmp_path, OK_OUTPUT, mode=0o644)
    result = probe_launcher(tmp_path)
    assert result.passed is False
    assert "Could not run the launcher" in result.detail
    assert result.returncode is None


# --------------------------------------------------------------------------- #
# The gate is stateless: it must not own a listener
# --------------------------------------------------------------------------- #

FORBIDDEN_IN_GATE = (
    "socket",
    "bind(",
    "AF_INET",
    "AF_UNIX",
    "setsockopt",
    "listen(",
    "accept(",
    "connect_ex",
    "SO_REUSEADDR",
    "start_new_session",
    "setsid",
    "pgid",
    "killpg",
    "os.kill",
    "SIGTERM",
    "SIGKILL",
    "signal.",
    "terminate(",
    "readiness",
    "time.sleep",
    "allocate_port",
    "free_port",
)


def test_gate_never_binds_allocates_or_polls_a_port(tmp_path):
    """A passing probe must be pure text exchange plus one exit status."""
    _write_launcher(tmp_path, OK_OUTPUT)
    assert probe_launcher(tmp_path).passed is True

    for token in FORBIDDEN_IN_GATE:
        assert token not in GATE_SOURCE, token
    assert "shell=True" not in GATE_SOURCE
    assert "shell=False" in GATE_SOURCE
    # No port arithmetic or allocation helpers either: the gate only reads what
    # the launcher printed.
    assert "getsockname" not in GATE_SOURCE
    assert "random" not in GATE_SOURCE


# --------------------------------------------------------------------------- #
# The Qt worker: one terminal result, no widgets
# --------------------------------------------------------------------------- #


def _recording_job(job):
    """Attach recorders to every terminal signal of *job*."""
    seen: dict[str, list[tuple]] = {"probe": [], "finished": [], "failed": []}
    job.signals.probe_finished.connect(lambda app_id, result: seen["probe"].append((app_id, result)))
    job.signals.save_finished.connect(lambda app_id, result: seen["finished"].append((app_id, result)))
    job.signals.save_failed.connect(lambda app_id, result: seen["failed"].append((app_id, result)))
    return seen


def test_job_emits_exactly_one_terminal_result(tmp_path):
    _write_launcher(tmp_path, OK_OUTPUT)
    job = config_jobs.LauncherProbeJob(_meta(tmp_path))
    seen = _recording_job(job)

    job.run()

    assert len(seen["probe"]) == 1
    assert seen["finished"] == [] and seen["failed"] == []
    app_id, result = seen["probe"][0]
    assert app_id == "chat2api"
    assert isinstance(result, LauncherProbeResult)
    assert result.passed is True
    assert result.returncode == 0


def test_job_reports_a_failed_gate_as_one_result(tmp_path):
    _write_launcher(tmp_path, 'printf "0.0.0.0\\n8000\\n"\necho "nope" >&2\n')
    job = config_jobs.LauncherProbeJob(_meta(tmp_path))
    seen = _recording_job(job)

    job.run()

    assert len(seen["probe"]) == 1
    app_id, result = seen["probe"][0]
    assert app_id == "chat2api"
    assert result.passed is False
    assert result.detail == "nope"


def test_job_converts_an_unexpected_error_into_one_failed_result(tmp_path, monkeypatch):
    _write_launcher(tmp_path, OK_OUTPUT)

    def explode(app_dir, **kwargs):
        raise RuntimeError("worker exploded")

    monkeypatch.setattr(config_jobs, "probe_launcher", explode)
    job = config_jobs.LauncherProbeJob(_meta(tmp_path))
    seen = _recording_job(job)

    job.run()

    assert len(seen["probe"]) == 1
    _, result = seen["probe"][0]
    assert isinstance(result, LauncherProbeResult)
    assert result.passed is False
    assert "worker exploded" in result.detail


def test_job_touches_no_widgets(tmp_path):
    _write_launcher(tmp_path, OK_OUTPUT)
    job = config_jobs.LauncherProbeJob(_meta(tmp_path))
    assert job.meta.id == "chat2api"
    assert job.signals is not None
    job.run()

    for token in ("QtWidgets", "QWidget", "QApplication", "setText", "QThread", "socket"):
        assert token not in JOBS_SOURCE, token


def test_signals_declare_string_and_object_payloads():
    class Payload:
        pass

    signals = config_jobs.ConfigJobSignals()
    delivered: list[tuple[str, str, object]] = []
    signals.save_finished.connect(lambda app_id, payload: delivered.append(("save_finished", app_id, payload)))
    signals.save_failed.connect(lambda app_id, payload: delivered.append(("save_failed", app_id, payload)))
    signals.probe_finished.connect(lambda app_id, payload: delivered.append(("probe_finished", app_id, payload)))

    payload = Payload()
    signals.save_finished.emit("chat2api", payload)
    signals.save_failed.emit("chat2api", payload)
    signals.probe_finished.emit("chat2api", payload)

    assert [name for name, _, _ in delivered] == ["save_finished", "save_failed", "probe_finished"]
    assert all(app_id == "chat2api" and got is payload for _, app_id, got in delivered)
