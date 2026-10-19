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
    class IsolatedSupervisor(mw.SupervisorManager):
        def refresh_status(self):
            pass
        def start_supervisor(self):
            pass
        def stop_supervisor(self):
            pass
        def restart_service(self, app_id):
            pass
    monkeypatch.setattr(mw, "SupervisorManager", IsolatedSupervisor)
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
