import argparse
import sys
from typing import List, Optional

from PyQt6.QtWidgets import QApplication

from ai_manager.ui.icons import configure_app_icon
from ai_manager.ui.main_window import MainWindow
from ai_manager.utils.path_locator import find_ai_workspace_root


def parse_arguments(argv: Optional[List[str]] = None) -> bool:
    """Return True when the app should start minimized to the tray.

    ``--minimized`` and its ``--tray`` alias both enable tray startup. Unknown
    arguments (e.g. Qt flags such as ``-platform offscreen``) are ignored so
    they can pass through to ``QApplication``.
    """
    parser = argparse.ArgumentParser(description="ai-manager desktop administration")
    parser.add_argument(
        "--minimized",
        "--tray",
        action="store_true",
        dest="minimized",
        help="Start minimized to the system tray",
    )
    args, _unknown = parser.parse_known_args(argv)
    return bool(args.minimized)


def main():
    minimized = parse_arguments()

    app = QApplication(sys.argv)
    configure_app_icon(app)
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName("ai-manager")

    workspace = find_ai_workspace_root()
    window = MainWindow(workspace_root=workspace, start_minimized_override=minimized)

    if not window.is_minimized_at_startup:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
