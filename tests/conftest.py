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

from pathlib import Path
import json
from ai_manager.config.app_registry import get_managed_apps
from ai_manager.config.models import UserSettings

CHAT = '{"server":{"host":"127.0.0.1","port":8000,"auth_token_env":null},"models":{"echo-1":{"provider":"echo"}}}\n'
BRIDGE = '# Local save destination\nsave_root: "../storage" # keep relative to config parent\nmax_text_bytes: 1048576\nport: 8964\n'
LLM = {
    "ai-grammar": '''server:
  host: 127.0.0.1
  port: 8766
# Keep debug and commented choices
debug: false
ai:
  api_base: "http://127.0.0.1:8000" # bridge endpoint
  api_key: "$CHAT2API_TOKEN"
  model: "original-grammar"
  #model: alternate-grammar
  timeout:
    connect: 10
    read: 300
cache:
  enabled: true
''',
    "textkit": '''host: 127.0.0.1
port: 8765
ai:
  api_base: "http://127.0.0.1:8000"
  api_key: "$CHAT2API_TOKEN"
  ocr:
    model: "original-ocr"
  text:
    model: "original-text"
  timeout:
    read: 1200
''',
    "yt2txt": '''host: "127.0.0.1"
port: 8666
ai:
  api_base: "http://127.0.0.1:8000"
  api_key: "$CHAT2API_TOKEN"
  model: "original-transcribe"
cache:
  enabled: true
''',
}


@pytest.fixture
def five_app_workspace(tmp_path):
    """Create the five registered application directories with real configs.

    Window-level tests build against this workspace instead of a copy of the
    three legacy LLM fixtures, so every lifecycle assertion also covers the two
    structured applications.
    """
    (tmp_path / "storage").mkdir()
    for app_id, meta in get_managed_apps(tmp_path).items():
        meta.relative_path.mkdir(parents=True)
        text = CHAT if app_id == "chat2api" else BRIDGE if app_id == "file-bridge" else LLM[app_id]
        (meta.relative_path / meta.config_file_name).write_text(text, encoding="utf-8")
        (meta.relative_path / meta.example_config_file_name).write_text(text, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def isolate_manager(monkeypatch):
    from ai_manager.ui import main_window as mw
    monkeypatch.setattr(mw, "load_user_settings", lambda: UserSettings())
    monkeypatch.setattr(mw, "save_user_settings", lambda settings: None)
    # The SupervisorManager class is deliberately NOT replaced here. Spawning is
    # already neutralised for every test by `_disable_supervisor_autostart`,
    # `_no_destructive_supervisor_commands` and `_no_real_status_probe`. Swapping
    # the class from an autouse fixture silently defeated the suite's autostart
    # assertions after these branches were merged.
    if hasattr(mw.MainWindow, "_start_launcher_probes"):
        from ai_manager.config.structured_models import LauncherProbeResult
        def passed(window):
            for app_id, meta in window.apps.items():
                if meta.config_kind == "chat2api":
                    window._on_launcher_probe_finished(app_id, LauncherProbeResult(True))
        # Keep the production starter reachable: tests that pin probe caching
        # call it explicitly and must never reach a live process.
        monkeypatch.setattr(
            mw.MainWindow,
            "_production_start_launcher_probes",
            mw.MainWindow._start_launcher_probes,
            raising=False,
        )
        monkeypatch.setattr(mw.MainWindow, "_start_launcher_probes", passed)
    from ai_manager.services.protocol_capability import ProtocolSupport, ProtocolSupportStatus

    def unknown_protocols(window):
        for app_id, meta in window.apps.items():
            if meta.supports_protocol_selection:
                support = ProtocolSupport(ProtocolSupportStatus.UNVERIFIABLE)
                window._protocol_support[app_id] = support
                window.views[app_id].set_protocol_support(support)

    monkeypatch.setattr(
        mw.MainWindow,
        "_production_start_protocol_probes",
        mw.MainWindow._start_protocol_probes,
        raising=False,
    )
    monkeypatch.setattr(mw.MainWindow, "_start_protocol_probes", unknown_protocols)


@pytest.fixture
def endpoint_window(qtbot, five_app_workspace, monkeypatch, request):
    """Real five-app coordinator with controlled jobs, restart and teardown."""
    from unittest.mock import MagicMock
    from PyQt6.QtWidgets import QMessageBox
    from ai_manager.ui.main_window import MainWindow

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Discard
    )
    prepare = getattr(request, "param", None)
    if prepare is not None:
        prepare(five_app_workspace, monkeypatch)
    window = MainWindow(workspace_root=five_app_workspace)
    qtbot.addWidget(window)
    window.thread_pool = MagicMock()
    monkeypatch.setattr(window.supervisor_manager, "restart_service", MagicMock())
    return window
