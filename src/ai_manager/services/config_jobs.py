"""Qt worker ownership for structured configuration jobs.

Workers run off the GUI thread and emit exactly one terminal result each through
their own ``ConfigJobSignals`` instance. They never touch widgets, never open
dialogs, and never display anything themselves: the receiver decides what the
result means. MainWindow keeps a job alive until its terminal signal arrives and
uses queued delivery into its own slots.

Task 7 installs the capability-gate worker (``LauncherProbeJob``). The save
worker is added by a later task.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from ai_manager.config.models import AppMetadata
from ai_manager.config.structured_models import LauncherProbeResult
from ai_manager.services.launcher_gate import probe_launcher


class ConfigJobSignals(QObject):
    """Terminal signals emitted by configuration workers."""

    save_finished = pyqtSignal(str, object)  # app_id, SaveResult
    save_failed = pyqtSignal(str, object)  # app_id, ConfigError
    probe_finished = pyqtSignal(str, object)  # app_id, LauncherProbeResult


class LauncherProbeJob(QRunnable):
    """Run the launcher capability gate off the GUI thread.

    Emits exactly one ``probe_finished(app_id, LauncherProbeResult)``. An
    unexpected failure is converted into a failed result rather than escaping
    the worker, so host/port stay gated instead of leaving the UI pending.
    """

    def __init__(self, meta: AppMetadata) -> None:
        super().__init__()
        self.meta = meta
        self.signals = ConfigJobSignals()

    def run(self) -> None:
        try:
            result = probe_launcher(self.meta.relative_path)
        except Exception as exc:  # never let a worker die without a result
            result = LauncherProbeResult(
                passed=False,
                detail=f"Launcher capability check failed: {exc}",
            )
        self.signals.probe_finished.emit(self.meta.id, result)
