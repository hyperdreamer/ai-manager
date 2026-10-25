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
        lambda self: calls.append(True) or True,
    )
    refreshed = []
    monkeypatch.setattr(
        SupervisorManager, "refresh_status", lambda self: refreshed.append(True)
    )

    win = MainWindow(workspace_root=tmp_path)
    qtbot.addWidget(win)
    win._poll_timer.stop()

    # The spy returns True (a claim); the constructor must not add its own
    # refresh on top of the entry point.
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

    window.show()
    assert window.isVisible()
    assert_constructor_claim(window)

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel
    )
    assert window.close() is False, "Cancel must ignore the close event"
    assert window.isVisible() is True
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
    # Interpolated values are bound to locals first: an interpolation that starts
    # a line would make textwrap.dedent leave the block indented.
    src_dir = str(Path.cwd() / "src")
    root_dir = str(Path.cwd())
    fixtures_dir = str(Path(__file__).parent / "fixtures")
    tmp_dir = str(tmp_path)
    env_name = AUTOSTART_DISABLE_ENV
    script = textwrap.dedent(
        f"""
        import os, sys, pathlib, shutil
        os.environ.pop({env_name!r}, None)   # opt in, or this is vacuous
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, {src_dir!r})
        sys.path.insert(0, {root_dir!r})

        from PyQt6.QtCore import QProcess, QTimer
        from PyQt6.QtWidgets import QApplication
        from ai_manager.services import supervisor as sup
        from tests.helpers import install_fake_status_process
        from ai_manager.config.models import UserSettings
        from ai_manager.ui import main_window as mw

        rec = []
        # ``sup.subprocess`` is the global subprocess module, so patching it also sees
        # every unrelated spawn in this process - including the protocol capability
        # probe, which legitimately runs a short-lived python child while the window
        # is constructed. Record supervisor commands only: this assertion is about a
        # supervisor start after quit, not about subprocess use in general.
        class Rec:
            def __call__(self, argv, *a, **k):
                if any("ai-backends" in str(part) for part in argv):
                    rec.append(list(argv))
                return object()
        sup.subprocess.Popen = Rec()
        sup.SupervisorManager.__init__ = install_fake_status_process(
            sup.SupervisorManager.__init__
        )
        sup.SupervisorManager._autostart_consumed = False
        sup.SupervisorManager._autostart_cancel_epoch = 0
        mw.load_user_settings = lambda: UserSettings()
        mw.save_user_settings = lambda s: None

        tmp = pathlib.Path({tmp_dir!r})
        fixtures = pathlib.Path({fixtures_dir!r})
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

        # A late stopped result after quit must not start anything.
        manager._status_process.finish()
        manager._status_output_buffer.clear()
        # chr(10) rather than a backslash-n: inside this f-string a backslash-n
        # would become a real newline in the child source and break its indent.
        manager._status_output_buffer.extend(
            b"[2026-10-04 11:47:44] supervisor not running" + bytes([10])
        )
        manager._on_status_finished(0, QProcess.ExitStatus.NormalExit)
        if rec:
            os._exit(10)                   # spawn after quit
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

    # B is constructed through the real entry point: the process-wide attempt is
    # already consumed, so B must not claim and must not launch a probe.
    second = MainWindow(workspace_root=tmp_path)
    qtbot.addWidget(second)
    second._poll_timer.stop()
    manager_b = second.supervisor_manager
    assert manager_b.claim_is_live() is False
    assert manager_b._status_process.starts == [], "B must not probe for autostart"

    manager_b.start_supervisor()
    manual = [list(argv) for argv in recorder]
    assert manual == [[manager_b.executable, "start"]]

    deliver(manager_a, SAMPLE_STOPPED_OUTPUT)
    assert [list(argv) for argv in recorder] == manual
