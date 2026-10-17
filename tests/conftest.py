import os

import pytest

# Set offscreen platform for headless pytest execution
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def mock_tray_available(monkeypatch):
    """Control ``QSystemTrayIcon.isSystemTrayAvailable`` from tests.

    Availability defaults to ``True`` so a test can simply request the
    fixture. Call the returned setter with ``False`` to simulate a display
    server without tray support without re-patching by hand.
    """
    from PyQt6.QtWidgets import QSystemTrayIcon

    def _set(available: bool = True) -> bool:
        monkeypatch.setattr(
            QSystemTrayIcon,
            "isSystemTrayAvailable",
            staticmethod(lambda: available),
        )
        return available

    _set(True)
    return _set


@pytest.fixture(autouse=True)
def _disable_supervisor_autostart(monkeypatch):
    """Keep every test from performing an automatic supervisor start.

    Production code honours this variable at the entry point, so ordinary tests
    never claim the one-shot attempt even if a window is constructed.
    """
    from ai_manager.services.supervisor import AUTOSTART_DISABLE_ENV

    monkeypatch.setenv(AUTOSTART_DISABLE_ENV, "1")


@pytest.fixture(autouse=True)
def _no_destructive_supervisor_commands(monkeypatch):
    """Fail the test if it spawns `ai-backends start` or `ai-backends stop`.

    `ai-backends start` is destructive (it kills the existing supervisor and every
    backend before starting fresh), so a test must never reach it. Read-only
    `status` polling is handled by ``_no_real_status_probe`` instead.
    """
    import subprocess
    from unittest.mock import MagicMock

    destructive = []
    real_popen = subprocess.Popen

    def guard(argv, *args, **kwargs):
        argv_list = [argv] if isinstance(argv, str) else list(argv)
        if len(argv_list) > 1 and argv_list[1] in {"start", "stop"}:
            destructive.append(argv_list)
            return MagicMock()
        return real_popen(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guard)
    yield
    assert destructive == [], f"tests must not spawn ai-backends: {destructive}"


@pytest.fixture(autouse=True)
def _no_real_status_probe(monkeypatch):
    """Give every ``SupervisorManager`` an inert status probe.

    ``refresh_status()`` calls ``QProcess.start(exe, ["status"])``, which the
    ``Popen`` guard cannot see. Without this wrapper the app's poll timer would
    exec the real `/home/bin/ai-backends` during ordinary window tests.
    """
    from ai_manager.services.supervisor import SupervisorManager
    from tests.helpers import install_fake_status_process

    monkeypatch.setattr(
        SupervisorManager,
        "__init__",
        install_fake_status_process(SupervisorManager.__init__),
    )


@pytest.fixture
def autostart_enabled(monkeypatch):
    """Opt in to autostart with the process-wide state reset and restored."""
    from ai_manager.services.supervisor import AUTOSTART_DISABLE_ENV, SupervisorManager

    monkeypatch.delenv(AUTOSTART_DISABLE_ENV, raising=False)
    monkeypatch.setattr(SupervisorManager, "_autostart_consumed", False)
    monkeypatch.setattr(SupervisorManager, "_autostart_cancel_epoch", 0)
    yield
