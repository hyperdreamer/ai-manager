"""Qt worker ownership for structured configuration jobs.

Workers run off the GUI thread and emit exactly one terminal result each through
their own ``ConfigJobSignals`` instance. They never touch widgets, never open
dialogs, and never display anything themselves: the receiver decides what the
result means. MainWindow keeps a job alive until its terminal signal arrives and
uses queued delivery into its own slots.

Task 7 installs the capability-gate worker (``LauncherProbeJob``). Task 9 adds
the save worker (``StructuredSaveJob``).
"""

from __future__ import annotations

import copy

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from ai_manager.config.models import AppMetadata
from ai_manager.config.structured_models import (
    DependentMatch,
    LauncherProbeResult,
    StructuredDoc,
)
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


class StructuredSaveJob(QRunnable):
    """Validate and commit one structured draft off the GUI thread.

    The job owns deep copies of the metadata, draft and dependent snapshots, so
    later widget edits cannot reach the commit. It emits exactly one terminal
    ``save_finished(app_id, SaveResult)`` or ``save_failed(app_id, ConfigError)``.
    """

    def __init__(
        self,
        meta: AppMetadata,
        draft: StructuredDoc,
        dependents: tuple[DependentMatch, ...] = (),
    ) -> None:
        super().__init__()
        self.meta = meta.model_copy(deep=True)
        self.draft = copy.deepcopy(draft)
        self.dependents = copy.deepcopy(dependents)
        self.signals = ConfigJobSignals()

    def run(self) -> None:
        from ai_manager.config.config_errors import ConfigError
        from ai_manager.config.structured_config import commit

        try:
            result = commit(
                self.meta.config_kind,
                self.draft.path,
                self.draft,
                self.draft.raw_sha256,
                dependents=self.dependents,
            )
        except ConfigError as exc:
            self.signals.save_failed.emit(self.meta.id, exc)
        except Exception as exc:  # never let a worker die without a terminal signal
            self.signals.save_failed.emit(
                self.meta.id, ConfigError(f"Configuration save failed: {exc}")
            )
        else:
            self.signals.save_finished.emit(self.meta.id, result)
