import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from ai_manager.resources import assets
from ai_manager.utils.path_locator import find_ai_workspace_root

APP_DESKTOP_DIR = Path.home() / ".local" / "share" / "applications"
AUTOSTART_DIR = Path.home() / ".config" / "autostart"
DESKTOP_FILE_NAME = "ai-manager.desktop"


class DesktopIntegrationService:
    """Manages FreeDesktop .desktop entries for menus and autostart."""

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or find_ai_workspace_root()

    def get_launcher_command(self, start_minimized: bool = False) -> str:
        """Resolves the launcher path with proper quoting.

        Priority:
        1. workspace_root / "start.sh" (when executable)
        2. shutil.which("ai-manager")
        3. sys.executable + " -m ai_manager.main"
        """
        start_script = self.workspace_root / "start.sh"
        if start_script.is_file() and os.access(start_script, os.X_OK):
            command = shlex.quote(str(start_script))
        else:
            which_cmd = shutil.which("ai-manager")
            if which_cmd:
                command = shlex.quote(which_cmd)
            else:
                command = f"{shlex.quote(sys.executable)} -m ai_manager.main"

        if start_minimized:
            command += " --minimized"
        return command

    def generate_desktop_entry(self, start_minimized: bool = False) -> str:
        """Returns FreeDesktop compliant .desktop file content."""
        icon_path = assets.asset_path("color")
        icon_value = str(icon_path) if icon_path is not None else "applications-development"
        lines = [
            "[Desktop Entry]",
            "Type=Application",
            "Name=ai-manager",
            "GenericName=AI Service Manager & Provider Configurator",
            "Comment=Configure AI models and supervise local AI backend services",
            f"Exec={self.get_launcher_command(start_minimized)}",
            f"Path={self.workspace_root}",
            f"Icon={icon_value}",
            "Terminal=false",
            "Categories=Development;Utility;Settings;",
            "StartupNotify=true",
            "StartupWMClass=ai-manager",
            "",
        ]
        return "\n".join(lines)

    def is_desktop_shortcut_installed(self) -> bool:
        path = APP_DESKTOP_DIR / DESKTOP_FILE_NAME
        return path.is_file() and os.access(path, os.R_OK)

    def install_desktop_shortcut(self) -> bool:
        try:
            APP_DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
            target = APP_DESKTOP_DIR / DESKTOP_FILE_NAME
            target.write_text(self.generate_desktop_entry(start_minimized=False), encoding="utf-8")
            self._update_desktop_database(APP_DESKTOP_DIR)
            return True
        except OSError:
            return False

    def remove_desktop_shortcut(self) -> bool:
        target = APP_DESKTOP_DIR / DESKTOP_FILE_NAME
        try:
            target.unlink()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return True

    def is_autostart_enabled(self) -> bool:
        return (AUTOSTART_DIR / DESKTOP_FILE_NAME).is_file()

    def set_autostart(self, enabled: bool, start_minimized: bool = False) -> bool:
        target = AUTOSTART_DIR / DESKTOP_FILE_NAME
        try:
            if enabled:
                AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    self.generate_desktop_entry(start_minimized=start_minimized),
                    encoding="utf-8",
                )
            else:
                target.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    @staticmethod
    def _update_desktop_database(directory: Path) -> None:
        """Best-effort refresh of the desktop entry database."""
        try:
            subprocess.run(
                ["update-desktop-database", str(directory)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            pass
