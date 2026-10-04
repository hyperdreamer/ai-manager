import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from PyQt6.QtCore import QObject, QProcess, pyqtSignal
from ai_manager.config.models import ServiceRunState, ServiceStatus, SupervisorStatus

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

    def __init__(self, workspace_root: Optional[Path] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.workspace_root = workspace_root
        self.executable = find_ai_backends_executable(workspace_root)
        self._status_process = QProcess(self)
        self._status_process.readyReadStandardOutput.connect(self._on_status_output)

        self._action_process = QProcess(self)
        self._action_process.finished.connect(self._on_action_finished)
        self._current_action: str = ""

    def refresh_status(self) -> None:
        """Runs `ai-backends status` asynchronously."""
        if self._status_process.state() == QProcess.ProcessState.NotRunning:
            self._status_process.start(self.executable, ["status"])

    def _on_status_output(self) -> None:
        raw_bytes = self._status_process.readAllStandardOutput().data()
        output = raw_bytes.decode("utf-8", errors="replace")
        status = parse_supervisor_status(output)
        self.status_updated.emit(status)

    def restart_service(self, service_name: str) -> None:
        """Runs `ai-backends restart <service_name>` asynchronously."""
        if self._action_process.state() != QProcess.ProcessState.NotRunning:
            self.action_completed.emit("restart", False, "Another supervisor command is in progress.")
            return

        self._current_action = f"restart {service_name}"
        self._action_process.start(self.executable, ["restart", service_name])

    def start_supervisor(self) -> None:
        """Runs `ai-backends start` in the background."""
        # ai-backends start runs in the foreground by default, so we can launch it detached
        try:
            subprocess.Popen([self.executable, "start"], start_new_session=True)
            self.action_completed.emit("start_supervisor", True, "Supervisor started.")
            self.refresh_status()
        except Exception as e:
            self.action_completed.emit("start_supervisor", False, f"Failed to start supervisor: {e}")

    def _on_action_finished(self, exit_code: int, exit_status) -> None:
        success = exit_code == 0
        stderr_bytes = self._action_process.readAllStandardError().data()
        msg = stderr_bytes.decode("utf-8", errors="replace").strip()
        if not msg:
            stdout_bytes = self._action_process.readAllStandardOutput().data()
            msg = stdout_bytes.decode("utf-8", errors="replace").strip()
        self.action_completed.emit(self._current_action, success, msg or f"Exited with code {exit_code}")
        self.refresh_status()
