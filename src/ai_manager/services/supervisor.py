import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import ClassVar, Dict, Optional, Tuple
from PyQt6.QtCore import QObject, QProcess, pyqtSignal
from ai_manager.config.models import ServiceRunState, ServiceStatus, SupervisorStatus

AUTOSTART_DISABLE_ENV = "AI_MANAGER_DISABLE_SUPERVISOR_AUTOSTART"
_AUTOSTART_DISABLED_VALUES = frozenset({"1", "true", "yes", "on"})

SUPERVISOR_RUNNING_RE = re.compile(
    r"^\[.*?\]\s+supervisor running:\s+(?P<pid>\d+)", re.MULTILINE
)
SUPERVISOR_NOT_RUNNING_RE = re.compile(
    r"^\[.*?\]\s+supervisor not running", re.MULTILINE
)
SERVICE_LINE_RE = re.compile(
    r"^(?P<name>[a-zA-Z0-9_\-]+)\s+(?P<state>running|stopped)\s+pid=(?P<pid>\d+|-)\s+log=(?P<log>\S+)",
    re.MULTILINE,
)


def find_ai_backends_executable(workspace_root: Optional[Path] = None) -> str:
    """Finds the ai-backends CLI script."""
    # First check workspace root
    if workspace_root:
        local_cand = workspace_root / "ai-backends"
        if local_cand.is_file():
            return str(local_cand)

    which_cmd = shutil.which("ai-backends")
    if which_cmd:
        return which_cmd

    # Common fallback path
    home_bin = Path("/home/bin/ai-backends")
    if home_bin.is_file():
        return str(home_bin)

    return "ai-backends"


def parse_supervisor_status(output: str) -> SupervisorStatus:
    """Parses stdout of `ai-backends status` into a SupervisorStatus object."""
    is_running = False
    supervisor_pid: Optional[int] = None

    running_match = SUPERVISOR_RUNNING_RE.search(output)
    if running_match:
        is_running = True
        supervisor_pid = int(running_match.group("pid"))
    elif SUPERVISOR_NOT_RUNNING_RE.search(output):
        is_running = False
        supervisor_pid = None

    services = {}
    for match in SERVICE_LINE_RE.finditer(output):
        s_name = match.group("name")
        s_state_str = match.group("state")
        s_pid_str = match.group("pid")
        s_log = match.group("log")

        pid_val = int(s_pid_str) if s_pid_str.isdigit() else None
        state_enum = (
            ServiceRunState.RUNNING if s_state_str == "running" else ServiceRunState.STOPPED
        )

        services[s_name] = ServiceStatus(
            service_id=s_name,
            state=state_enum,
            pid=pid_val,
            log_path=s_log,
        )

    return SupervisorStatus(
        is_running=is_running,
        supervisor_pid=supervisor_pid,
        services=services,
    )


class SupervisorManager(QObject):
    """Asynchronous supervisor runner using QProcess."""

    status_updated = pyqtSignal(SupervisorStatus)
    action_completed = pyqtSignal(str, bool, str)  # action_name, success, message

    # Process-wide autostart state. Set at claim time and never cleared, so the
    # attempt happens at most once per process no matter how many windows exist.
    # Always accessed as ``SupervisorManager.<name>``; never via ``self``.
    _autostart_consumed: ClassVar[bool] = False
    _autostart_cancel_epoch: ClassVar[int] = 0

    # (action name, success message, failure template) per spawnable command.
    _ACTIONS: ClassVar[Dict[str, Tuple[str, str, str]]] = {
        "start": (
            "start_supervisor",
            "Supervisor started.",
            "Failed to start supervisor: {}",
        ),
        "stop": (
            "stop_supervisor",
            "Supervisor stopped.",
            "Failed to stop supervisor: {}",
        ),
    }

    def __init__(self, workspace_root: Optional[Path] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.workspace_root = workspace_root
        self.executable = find_ai_backends_executable(workspace_root)
        self._autostart_epoch: Optional[int] = None
        self._status_process = QProcess(self)
        self._status_output_buffer = bytearray()
        self._status_process.readyReadStandardOutput.connect(self._on_status_ready_read)
        self._status_process.finished.connect(self._on_status_finished)
        self._status_process.errorOccurred.connect(self._on_status_error)

        self._action_process = QProcess(self)
        self._action_process.finished.connect(self._on_action_finished)
        self._current_action: str = ""

    def refresh_status(self) -> None:
        """Runs `ai-backends status` asynchronously."""
        if self._status_process.state() == QProcess.ProcessState.NotRunning:
            self._status_output_buffer.clear()
            self._status_process.start(self.executable, ["status"])

    @staticmethod
    def autostart_disabled() -> bool:
        """True when the environment opts out of the automatic startup attempt."""
        raw = os.environ.get(AUTOSTART_DISABLE_ENV)
        if raw is None:
            return False
        return raw.strip().lower() in _AUTOSTART_DISABLED_VALUES

    def claim_is_live(self) -> bool:
        """True while this manager holds an uncancelled autostart claim."""
        return (
            self._autostart_epoch is not None
            and self._autostart_epoch == SupervisorManager._autostart_cancel_epoch
        )

    def start_if_not_running(self) -> bool:
        """Probe once, and start the supervisor only if it is really stopped.

        Returns True when this call claimed the process-wide attempt and launched
        a probe. Guard order matters: the busy check must precede the claim so a
        True return always means a probe was actually issued.
        """
        if self.autostart_disabled():
            return False
        if SupervisorManager._autostart_consumed:
            return False
        if self._status_process.state() != QProcess.ProcessState.NotRunning:
            return False
        SupervisorManager._autostart_consumed = True
        self._autostart_epoch = SupervisorManager._autostart_cancel_epoch
        self.refresh_status()
        return True

    def cancel_pending_autostart(self) -> None:
        """Cancel any pending automatic start, process-wide.

        Advancing the shared epoch invalidates a claim held by *any* manager;
        clearing the instance epoch also marks this manager's own claim dead.
        The consumed flag is never restored: the attempt is one per process.
        """
        SupervisorManager._autostart_cancel_epoch += 1
        self._autostart_epoch = None

    def _on_status_ready_read(self) -> None:
        self._status_output_buffer.extend(self._status_process.readAllStandardOutput().data())

    def _on_status_finished(self, exit_code: int, exit_status) -> None:
        output = self._status_output_buffer.decode("utf-8", errors="replace")
        status = parse_supervisor_status(output)

        # Clear before emitting: a receiver that re-enters must not see a live
        # claim. A non-claimant's epoch is None, so this is a no-op for it.
        claim_epoch = self._autostart_epoch
        self._autostart_epoch = None

        self.status_updated.emit(status)

        authorized = (
            exit_code == 0
            and exit_status == QProcess.ExitStatus.NormalExit
            and SUPERVISOR_NOT_RUNNING_RE.search(output) is not None
            and SUPERVISOR_RUNNING_RE.search(output) is None
        )
        if claim_epoch != SupervisorManager._autostart_cancel_epoch:
            return
        if not authorized:
            return
        if self._spawn_supervisor("start", silent=True):
            self.refresh_status()

    def _on_status_error(self, error) -> None:
        # A probe that could not run never authorises an automatic start.
        self._autostart_epoch = None
        status = SupervisorStatus(is_running=False, supervisor_pid=None, services={})
        self.status_updated.emit(status)

    def restart_service(self, service_name: str) -> None:
        """Runs `ai-backends restart <service_name>` asynchronously."""
        if self._action_process.state() != QProcess.ProcessState.NotRunning:
            self.action_completed.emit("restart", False, "Another supervisor command is in progress.")
            return

        self._current_action = f"restart {service_name}"
        self._action_process.start(self.executable, ["restart", service_name])

    def _spawn_supervisor(self, command: str, *, silent: bool) -> bool:
        """Run `ai-backends <command>` detached; return whether it was launched.

        ``silent`` suppresses ``action_completed`` so an automatic attempt can
        never raise the user-facing failure dialog for something nobody asked for.
        """
        action, ok_message, fail_template = self._ACTIONS[command]
        try:
            subprocess.Popen([self.executable, command], start_new_session=True)
        except Exception as e:
            if not silent:
                self.action_completed.emit(action, False, fail_template.format(e))
            return False
        if not silent:
            self.action_completed.emit(action, True, ok_message)
        return True

    def start_supervisor(self) -> None:
        """Runs `ai-backends start` in the background."""
        self.cancel_pending_autostart()
        if self._spawn_supervisor("start", silent=False):
            self.refresh_status()

    def stop_supervisor(self) -> None:
        """Runs `ai-backends stop` in the background."""
        self.cancel_pending_autostart()
        if self._spawn_supervisor("stop", silent=False):
            self.refresh_status()

    def _on_action_finished(self, exit_code: int, exit_status) -> None:
        success = exit_code == 0
        stderr_bytes = self._action_process.readAllStandardError().data()
        msg = stderr_bytes.decode("utf-8", errors="replace").strip()
        if not msg:
            stdout_bytes = self._action_process.readAllStandardOutput().data()
            msg = stdout_bytes.decode("utf-8", errors="replace").strip()
        self.action_completed.emit(self._current_action, success, msg or f"Exited with code {exit_code}")
        self.refresh_status()


def default_log_path(service_id: str) -> Path:
    """Return ~/.cache/ai-backends/logs/<service_id>.log.

    Used only when no log_path has ever been reported for this service.
    """
    return Path.home() / ".cache" / "ai-backends" / "logs" / f"{service_id}.log"
