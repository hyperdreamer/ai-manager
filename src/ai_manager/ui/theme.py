from ai_manager.config.models import ThemeMode

DARK_QSS = """
QMainWindow, QWidget#centralWidget {
    background-color: #18181f;
    color: #e0e0e0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

QToolBar {
    background-color: #20202a;
    border-bottom: 1px solid #33333f;
    padding: 6px 12px;
    spacing: 8px;
}

/* Sidebar */
QListWidget#appSidebarList {
    background-color: #1b1b22;
    border: none;
    border-right: 1px solid #2d2d38;
    padding: 8px 6px;
}
QListWidget#appSidebarList::item {
    border-radius: 6px;
    padding: 8px 10px;
    margin: 2px 0px;
    color: #d1d5db;
}
QListWidget#appSidebarList::item:selected {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QListWidget#appSidebarList::item:hover:!selected {
    background-color: #242430;
}

/* Group Boxes & Containers */
QGroupBox {
    background-color: #20202a;
    border: 1px solid #2e2e3d;
    border-radius: 8px;
    margin-top: 20px;
    padding: 14px;
    font-weight: 600;
    color: #f3f4f6;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
}

/* Inputs */
QLineEdit, QComboBox {
    background-color: #121217;
    border: 1px solid #3e3e4f;
    border-radius: 5px;
    padding: 6px 10px;
    color: #f3f4f6;
    selection-background-color: #2563eb;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
}

/* Buttons */
QPushButton {
    background-color: #2e303e;
    color: #e0e0e0;
    border: 1px solid #3e4052;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #383a4c;
}
QPushButton:pressed {
    background-color: #242531;
}

QPushButton#primaryActionBtn {
    background-color: #ea580c;
    color: #ffffff;
    border: 1px solid #c2410c;
    font-weight: 600;
}
QPushButton#primaryActionBtn:hover {
    background-color: #c2410c;
}

QPushButton#fetchBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
}
QPushButton#fetchBtn:hover {
    background-color: #1d4ed8;
}

/* Status Badges */
QLabel#statusBadgeRunning {
    color: #10b981;
    font-weight: 600;
}
QLabel#statusBadgeStopped {
    color: #9ca3af;
    font-weight: 600;
}
QLabel#statusBadgeTransitioning {
    color: #f59e0b;
    font-weight: 600;
}

/* Model Tag Chips */
QToolButton#modelChip {
    background-color: #282a36;
    border: 1px solid #3e4052;
    border-radius: 10px;
    padding: 3px 8px;
    font-size: 11px;
    color: #93c5fd;
}
QToolButton#modelChip:hover {
    background-color: #374151;
    border-color: #60a5fa;
    color: #ffffff;
}

/* Action Footer */
QFrame#footerActionBar {
    background-color: #18181f;
    border-top: 1px solid #2a2a35;
    padding-top: 12px;
}
"""

LIGHT_QSS = """
QMainWindow, QWidget#centralWidget {
    background-color: #ffffff;
    color: #1e293b;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

QToolBar {
    background-color: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
    padding: 6px 12px;
    spacing: 8px;
}

/* Sidebar */
QListWidget#appSidebarList {
    background-color: #f1f5f9;
    border: none;
    border-right: 1px solid #e2e8f0;
    padding: 8px 6px;
}
QListWidget#appSidebarList::item {
    border-radius: 6px;
    padding: 8px 10px;
    margin: 2px 0px;
    color: #334155;
}
QListWidget#appSidebarList::item:selected {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QListWidget#appSidebarList::item:hover:!selected {
    background-color: #e2e8f0;
}

/* Group Boxes & Containers */
QGroupBox {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    margin-top: 20px;
    padding: 14px;
    font-weight: 600;
    color: #1e293b;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
}

/* Inputs */
QLineEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    padding: 6px 10px;
    color: #0f172a;
    selection-background-color: #2563eb;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #2563eb;
}

/* Buttons */
QPushButton {
    background-color: #ffffff;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #f1f5f9;
}
QPushButton:pressed {
    background-color: #e2e8f0;
}

QPushButton#primaryActionBtn {
    background-color: #ea580c;
    color: #ffffff;
    border: 1px solid #c2410c;
    font-weight: 600;
}
QPushButton#primaryActionBtn:hover {
    background-color: #c2410c;
}

QPushButton#fetchBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
}
QPushButton#fetchBtn:hover {
    background-color: #1d4ed8;
}

/* Status Badges */
QLabel#statusBadgeRunning {
    color: #059669;
    font-weight: 600;
}
QLabel#statusBadgeStopped {
    color: #64748b;
    font-weight: 600;
}
QLabel#statusBadgeTransitioning {
    color: #d97706;
    font-weight: 600;
}

/* Model Tag Chips */
QToolButton#modelChip {
    background-color: #eff6ff;
    border: 1px solid #bfdbfe;
    border-radius: 10px;
    padding: 3px 8px;
    font-size: 11px;
    color: #1e40af;
}
QToolButton#modelChip:hover {
    background-color: #dbeafe;
    color: #1e3a8a;
}

/* Action Footer */
QFrame#footerActionBar {
    background-color: #ffffff;
    border-top: 1px solid #f1f5f9;
    padding-top: 12px;
}
"""


def get_stylesheet(theme: ThemeMode) -> str:
    """Returns the CSS stylesheet string for the requested theme."""
    return LIGHT_QSS if theme == ThemeMode.LIGHT else DARK_QSS
