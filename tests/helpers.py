"""Shared test doubles for the supervisor autostart suites.

`FakeStatusProcess` stands in for `SupervisorManager._status_process` so a test
can drive the probe's lifecycle deterministically without ever starting the real
`ai-backends` script. `install_fake_status_process` wraps
`SupervisorManager.__init__` so every manager constructed in a test already owns a
fake *before* the constructor returns — which is what keeps `MainWindow.__init__`'s
autostart probe from exec'ing the real executable.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from PyQt6.QtCore import QProcess


class FakeStatusProcess:
    """Inert stand-in for the status QProcess.

    Mirrors the slice of the QProcess surface `SupervisorManager` uses:
    `state()` and `start(program, args)`. It records every start request and
    flips its own state, but it never spawns anything.
    """

    def __init__(self) -> None:
        self._state: QProcess.ProcessState = QProcess.ProcessState.NotRunning
        self.starts: List[List[str]] = []

    def state(self) -> QProcess.ProcessState:
        return self._state

    def start(self, program: str, args: Optional[List[str]] = None) -> None:
        self.starts.append([program, *(args or [])])
        self._state = QProcess.ProcessState.Running

    def finish(self) -> None:
        """Simulate the probe completing, so a later probe may be launched."""
        self._state = QProcess.ProcessState.NotRunning


def install_fake_status_process(
    original_init: Callable[..., None],
) -> Callable[..., None]:
    """Wrap a `SupervisorManager.__init__` so every instance gets an inert probe.

    The real `QProcess` created by the original initialiser is left idle and
    replaced immediately, so nothing dereferences the swapped-out object.
    """

    def wrapped(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._status_process = FakeStatusProcess()

    return wrapped
