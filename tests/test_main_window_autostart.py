"""MainWindow wiring for the one-shot supervisor autostart attempt.

The constructor claims the process-wide attempt and starts a probe. These tests
therefore assert the *constructor's* claim instead of arming a second time: with a
monotone process-wide flag, a second `start_if_not_running()` returns False and
`arm()` would fail against correct code.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QApplication, QMessageBox

from ai_manager.config.models import UserSettings
from ai_manager.services.supervisor import AUTOSTART_DISABLE_ENV, SupervisorManager
from ai_manager.ui import main_window as main_window_module
from ai_manager.ui.main_window import MainWindow
from tests.helpers import FakeStatusProcess

SAMPLE_STOPPED_OUTPUT = """[2026-10-04 11:47:44] supervisor not running
ai-grammar   stopped  pid=- log=/home/henry/.cache/ai-backends/logs/ai-grammar.log
"""


def _copy_fixtures(tmp_path: Path) -> None:
    fixtures_dir = Path(__file__).parent / "fixtures"
    for name in ("ai-grammar", "textkit", "yt2txt"):
        (tmp_path / name / "backend").mkdir(parents=True)
    for src, dest in [
        ("ai_grammar_config.yaml", tmp_path / "ai-grammar" / "backend" / "config.yaml"),
        ("textkit_unified_config.yaml", tmp_path / "textkit" / "backend" / "config.yaml"),
        ("yt2txt_config.yaml", tmp_path / "yt2txt" / "backend" / "config.yaml"),
    ]:
        shutil.copy2(fixtures_dir / src, dest)


@pytest.fixture
def recorder(monkeypatch):
    recorded = []

    def fake_popen(argv, *args, **kwargs):
        recorded.append(list(argv) if not isinstance(argv, str) else [argv])
        return MagicMock()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return recorded


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, recorder, autostart_enabled):
    _copy_fixtures(tmp_path)
    monkeypatch.setattr(main_window_module, "load_user_settings", lambda: UserSettings())
    monkeypatch.setattr(main_window_module, "save_user_settings", lambda s: None)
    win = MainWindow(workspace_root=tmp_path)
    qtbot.addWidget(win)
    win._poll_timer.stop()
    return win


def deliver(manager, output, code=0, status=QProcess.ExitStatus.NormalExit):
    manager._status_process.finish()
    manager._status_output_buffer.clear()
    manager._status_output_buffer.extend(output.encode("utf-8"))
    manager._on_status_finished(code, status)


def assert_constructor_claim(window, probes=None):
    manager = window.supervisor_manager
    probes = probes if probes is not None else manager._status_process
    assert len(probes.starts) == 1
    assert SupervisorManager._autostart_consumed is True
    assert manager.claim_is_live() is True


def test_constructor_requests_one_attempt(qtbot, tmp_path, monkeypatch, recorder):
    _copy_fixtures(tmp_path)
    monkeypatch.setattr(main_window_module, "load_user_settings", lambda: UserSettings())
    monkeypatch.setattr(main_window_module, "save_user_settings", lambda s: None)

    calls = []
    monkeypatch.setattr(
        SupervisorManager,
        "start_if_not_running",
        lambda self: calls.append(True) or False,
    )
    refreshed = []
    monkeypatch.setattr(
        SupervisorManager, "refresh_status", lambda self: refreshed.append(True)
    )

    win = MainWindow(workspace_root=tmp_path)
    qtbot.addWidget(win)
    win._poll_timer.stop()

    assert calls == [True]
    assert refreshed == []


def test_quit_cancels_pending_autostart(window, recorder):
    assert_constructor_claim(window)
    window._exit_application()

    manager = window.supervisor_manager
    assert manager.claim_is_live() is False
    assert manager._autostart_epoch is None

    deliver(manager, SAMPLE_STOPPED_OUTPUT)
    assert recorder == []


def test_hiding_to_tray_keeps_pending_autostart(
    window, recorder, monkeypatch, mock_tray_available
):
    mock_tray_available(True)
    window.settings.close_to_tray = True
    window.settings.first_close_notice_shown = True
    window.show()
    assert window.isVisible()

    assert_constructor_claim(window)

    assert window.close() is False
    assert window.isHidden() is True
    assert window.supervisor_manager.claim_is_live() is True


def test_cancel_in_the_unsaved_changes_prompt_keeps_the_attempt(window, recorder, monkeypatch):
    monkeypatch.setattr(window, "has_unsaved_changes", lambda: True)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel
    )

    assert_constructor_claim(window)
    window.handle_quit()

    assert window.supervisor_manager.claim_is_live() is True
    assert window.supervisor_manager._autostart_epoch is not None


def test_close_event_unsaved_prompt_path_keeps_the_attempt_until_confirmed(
    window, recorder, monkeypatch, mock_tray_available
):
    mock_tray_available(True)
    window.settings.close_to_tray = False
    monkeypatch.setattr(window, "has_unsaved_changes", lambda: True)

    assert_constructor_claim(window)

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel
    )
    window.close()
    manager = window.supervisor_manager
    assert manager.claim_is_live() is True
    assert manager._autostart_epoch is not None

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard
    )
    window.close()
    assert manager.claim_is_live() is False
    assert manager._autostart_epoch is None

    deliver(manager, SAMPLE_STOPPED_OUTPUT)
    assert recorder == []


def test_direct_app_quit_cancels_via_about_to_quit(tmp_path):
    """A direct `app.quit()` must still cancel: real event loop, isolated child.

    The claim must come from the *constructor* so this test exercises the
    `aboutToQuit` connection rather than `_exit_application` (which `app.quit()`
    never calls).
    """
    script = textwrap.dedent(
        f"""
        import os, sys, pathlib, shutil
        os.environ.pop({AUTOSTART_DISABLE_ENV!r}, None)   # opt in, or this is vacuous
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, {str(Path.cwd() / "src")!r})
        sys.path.insert(0, {str(Path.cwd())!r})

        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        from ai_manager.services import supervisor as sup
        from tests.helpers import install_fake_status_process
        from ai_manager.config.models import UserSettings
        from ai_manager.ui import main_window as mw

        rec = []
        class Rec:
            def __call__(self, argv, *a, **k):
                rec.append(list(argv)); return object()
        sup.subprocess.Popen = Rec()
        sup.SupervisorManager.__init__ = install_fake_status_process(
            sup.SupervisorManager.__init__
        )
        sup.SupervisorManager._autostart_consumed = False
        sup.SupervisorManager._autostart_cancel_epoch = 0
        mw.load_user_settings = lambda: UserSettings()
        mw.save_user_settings = lambda s: None

        tmp = pathlib.Path({str(tmp_path)!r})
        fixtures = pathlib.Path({str(Path(__file__).parent / "fixtures")!r})
        for name in ("ai-grammar", "textkit", "yt2txt"):
            (tmp / name / "backend").mkdir(parents=True, exist_ok=True)
        for src, dest in [
            ("ai_grammar_config.yaml", tmp / "ai-grammar" / "backend" / "config.yaml"),
            ("textkit_unified_config.yaml", tmp / "textkit" / "backend" / "config.yaml"),
            ("yt2txt_config.yaml", tmp / "yt2txt" / "backend" / "config.yaml"),
        ]:
            shutil.copy2(fixtures / src, dest)

        app = QApplication([])
        win = mw.MainWindow(workspace_root=tmp)
        win._poll_timer.stop()
        manager = win.supervisor_manager

        # The constructor's own claim, not a hand-made one.
        if not manager.claim_is_live():
            os._exit(6)
        if len(manager._status_process.starts) != 1:
            os._exit(7)

        emitted = []
        app.aboutToQuit.connect(lambda: emitted.append(True))
        quit_calls = []
        win._exit_application = lambda: quit_calls.append(True)

        QTimer.singleShot(0, app.quit)
        QTimer.singleShot(3000, lambda: os._exit(5))   # hard watchdog
        app.exec()

        # Asserts must run AFTER exec() returns: app.quit() ends the loop at once,
        # so any post-quit timer would never fire and this test would pass
        # vacuously (observed during implementation).
        if not emitted:
            os._exit(3)                    # aboutToQuit never fired
        if quit_calls:
            os._exit(8)                    # app.quit() must not route through it
        if manager.claim_is_live():
            os._exit(4)                    # claim survived the quit
        if manager._autostart_epoch is not None:
            os._exit(9)                    # instance field not cleared
        os._exit(0)
        """
    )
    env = dict(os.environ)
    env.pop(AUTOSTART_DISABLE_ENV, None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        cwd=str(Path.cwd()),
    )
    assert completed.returncode == 0, (
        f"child exited {completed.returncode}\n"
        f"stdout={completed.stdout}\nstderr={completed.stderr}"
    )


def test_manual_start_from_another_window_cancels_pending_attempt(
    window, recorder, monkeypatch, qtbot, tmp_path
):
    manager_a = window.supervisor_manager
    assert_constructor_claim(window)

    # A second window cannot claim the process-wide attempt.
    monkeypatch.setattr(
        SupervisorManager, "start_if_not_running", lambda self: False, raising=True
    )
    second = MainWindow(workspace_root=tmp_path)
    qtbot.addWidget(second)
    second._poll_timer.stop()
    assert second.supervisor_manager.claim_is_live() is False

    second.supervisor_manager.start_supervisor()
    manual = [list(argv) for argv in recorder]
    assert manual == [[second.supervisor_manager.executable, "start"]]

    deliver(manager_a, SAMPLE_STOPPED_OUTPUT)
    assert [list(argv) for argv in recorder] == manual
