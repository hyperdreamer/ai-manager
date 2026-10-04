import sys
from PyQt6.QtWidgets import QApplication
from ai_manager.ui.main_window import MainWindow
from ai_manager.utils.path_locator import find_ai_workspace_root


def main():
    app = QApplication(sys.argv)
    workspace = find_ai_workspace_root()
    window = MainWindow(workspace)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
