"""Qt workers and GUI delivery for configuration and capability jobs.

Workers own their inputs and emit terminal results without touching widgets.
MainWindow retains each worker until queued delivery into its GUI context.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from ai_manager.config.models import AppMetadata
from ai_manager.config.structured_models import (
    DependentMatch,
    LauncherProbeResult,
    StructuredDoc,
)
from ai_manager.services.launcher_gate import probe_launcher
from ai_manager.services.protocol_capability import (
    ProtocolSupport,
    _probe_protocol_support_at_generation,
    _unknown,
)

if TYPE_CHECKING:
    from ai_manager.ui.main_window import MainWindow


class ConfigJobSignals(QObject):
    """Terminal signals emitted by configuration workers."""

    save_finished = pyqtSignal(str, object)  # app_id, SaveResult
    save_failed = pyqtSignal(str, object)  # app_id, ConfigError
    probe_finished = pyqtSignal(str, object)  # app_id, launcher or protocol support


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


class ProtocolProbeJob(QRunnable):
    """Probe an owned app at the generation captured before queueing."""

    def __init__(self, meta: AppMetadata, token: int, generation: int) -> None:
        super().__init__()
        self.meta = meta.model_copy(deep=True)
        self._token, self._generation = token, generation
        self.signals = ConfigJobSignals()

    @property
    def token(self) -> int:
        return self._token

    @property
    def generation(self) -> int:
        return self._generation

    def run(self) -> None:
        try:
            result = _probe_protocol_support_at_generation(
                self.meta, generation=self.generation
            )
        except Exception as exc:
            result = _unknown(f"Protocol capability check failed: {exc}")
        self.signals.probe_finished.emit(self.meta.id, result)


class ProtocolProbeDelivery(QObject):
    """Carry immutable worker context through a GUI-owned queued slot."""

    def __init__(self, window: MainWindow, app_id: str, token: int, generation: int) -> None:
        super().__init__(window)
        self._window = window
        self._app_id, self._token, self._generation = app_id, token, generation

    @pyqtSlot(str, object)
    def finished(self, emitted_id: str, support: ProtocolSupport) -> None:
        if emitted_id == self._app_id:
            self._window._on_protocol_probe_finished(
                self._app_id, self._token, self._generation, support
            )


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
