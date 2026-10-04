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
