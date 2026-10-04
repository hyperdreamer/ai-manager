import os
import shlex
import sys
from pathlib import Path

import pytest

from ai_manager.services import desktop_integration
from ai_manager.services.desktop_integration import DesktopIntegrationService


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Redirect the module-level FreeDesktop directories into tmp_path."""
    app_dir = tmp_path / "applications"
    autostart_dir = tmp_path / "autostart"
    monkeypatch.setattr(desktop_integration, "APP_DESKTOP_DIR", app_dir)
    monkeypatch.setattr(desktop_integration, "AUTOSTART_DIR", autostart_dir)
    # Ensure this test never touches the real user directories.
    assert app_dir != Path.home() / ".local" / "share" / "applications"
    assert autostart_dir != Path.home() / ".config" / "autostart"
    return app_dir, autostart_dir


def test_get_launcher_command_prefers_executable_start_sh(tmp_path):
    start_sh = tmp_path / "start.sh"
    start_sh.write_text("#!/bin/sh\nexec ai-manager \"$@\"\n")
    start_sh.chmod(0o755)

    service = DesktopIntegrationService(workspace_root=tmp_path)
    assert service.get_launcher_command() == shlex.quote(str(start_sh))


def test_get_launcher_command_ignores_non_executable_start_sh(tmp_path, monkeypatch):
    start_sh = tmp_path / "start.sh"
    start_sh.write_text("#!/bin/sh\n")
    start_sh.chmod(0o644)

    monkeypatch.setattr(
        desktop_integration.shutil, "which", lambda name: "/usr/local/bin/ai-manager"
    )
    service = DesktopIntegrationService(workspace_root=tmp_path)
    assert service.get_launcher_command() == "/usr/local/bin/ai-manager"


def test_get_launcher_command_falls_back_to_python_module(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_integration.shutil, "which", lambda name: None)
    service = DesktopIntegrationService(workspace_root=tmp_path)
    command = service.get_launcher_command()
    assert command == f"{shlex.quote(sys.executable)} -m ai_manager.main"


def test_get_launcher_command_appends_minimized(tmp_path):
    start_sh = tmp_path / "start.sh"
    start_sh.write_text("#!/bin/sh\n")
    start_sh.chmod(0o755)

    service = DesktopIntegrationService(workspace_root=tmp_path)
    assert service.get_launcher_command(start_minimized=True).endswith(" --minimized")


def test_get_launcher_command_quotes_paths_with_spaces(tmp_path):
    spaced = tmp_path / "my workspace"
    spaced.mkdir()
    start_sh = spaced / "start.sh"
    start_sh.write_text("#!/bin/sh\n")
    start_sh.chmod(0o755)

    service = DesktopIntegrationService(workspace_root=spaced)
    command = service.get_launcher_command()
    assert command == shlex.quote(str(start_sh))
    assert " " not in command or command.startswith("'")


def test_generate_desktop_entry_contains_required_keys(tmp_path):
    service = DesktopIntegrationService(workspace_root=tmp_path)
    content = service.generate_desktop_entry()

    assert content.startswith("[Desktop Entry]\n")
    assert "Type=Application" in content
    assert "Name=ai-manager" in content
    assert "GenericName=AI Service Manager & Provider Configurator" in content
    assert "Comment=Configure AI models and supervise local AI backend services" in content
    assert f"Exec={service.get_launcher_command()}" in content
    assert f"Path={tmp_path}" in content
    assert "Icon=utilities-system-monitor" in content
    assert "Terminal=false" in content
    assert "Categories=Development;Utility;Settings;" in content
    assert "StartupNotify=true" in content
    assert "StartupWMClass=ai-manager" in content


def test_generate_desktop_entry_minimized_flag(tmp_path):
    service = DesktopIntegrationService(workspace_root=tmp_path)
    content = service.generate_desktop_entry(start_minimized=True)
    assert " --minimized" in content


def test_install_remove_and_detect_desktop_shortcut(tmp_path, isolated_dirs):
    app_dir, _ = isolated_dirs
    service = DesktopIntegrationService(workspace_root=tmp_path)

    assert service.is_desktop_shortcut_installed() is False

    assert service.install_desktop_shortcut() is True
    target = app_dir / "ai-manager.desktop"
    assert target.is_file()
    assert target.read_text() == service.generate_desktop_entry()
    assert service.is_desktop_shortcut_installed() is True

    assert service.remove_desktop_shortcut() is True
    assert not target.exists()
    assert service.is_desktop_shortcut_installed() is False


def test_remove_desktop_shortcut_is_idempotent(tmp_path, isolated_dirs):
    service = DesktopIntegrationService(workspace_root=tmp_path)
    # Already absent -> still reports success.
    assert service.remove_desktop_shortcut() is True


def test_install_desktop_shortcut_swallows_missing_update_desktop_database(
    tmp_path, isolated_dirs, monkeypatch
):
    app_dir, _ = isolated_dirs

    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("update-desktop-database not found")

    monkeypatch.setattr(desktop_integration.subprocess, "run", raise_missing)
    service = DesktopIntegrationService(workspace_root=tmp_path)
    assert service.install_desktop_shortcut() is True
    assert (app_dir / "ai-manager.desktop").is_file()


def test_install_desktop_shortcut_runs_update_desktop_database(
    tmp_path, isolated_dirs, monkeypatch
):
    app_dir, _ = isolated_dirs
    calls = []

    def record(args, **kwargs):
        calls.append(args)

    monkeypatch.setattr(desktop_integration.subprocess, "run", record)
    service = DesktopIntegrationService(workspace_root=tmp_path)
    assert service.install_desktop_shortcut() is True
    assert calls == [["update-desktop-database", str(app_dir)]]


def test_autostart_toggle(tmp_path, isolated_dirs):
    _, autostart_dir = isolated_dirs
    service = DesktopIntegrationService(workspace_root=tmp_path)
    target = autostart_dir / "ai-manager.desktop"

    assert service.is_autostart_enabled() is False

    assert service.set_autostart(True, start_minimized=True) is True
    assert target.is_file()
    assert service.is_autostart_enabled() is True
    assert " --minimized" in target.read_text()

    assert service.set_autostart(False) is True
    assert not target.exists()
    assert service.is_autostart_enabled() is False


def test_set_autostart_disable_is_idempotent(tmp_path, isolated_dirs):
    service = DesktopIntegrationService(workspace_root=tmp_path)
    assert service.set_autostart(False) is True


def test_default_workspace_root_uses_locator(monkeypatch, tmp_path):
    monkeypatch.setattr(
        desktop_integration, "find_ai_workspace_root", lambda: tmp_path
    )
    service = DesktopIntegrationService()
    assert service.workspace_root == tmp_path
    assert os.fspath(service.workspace_root) == os.fspath(tmp_path)
