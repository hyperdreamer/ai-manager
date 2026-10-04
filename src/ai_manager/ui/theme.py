from ai_manager.config.models import ThemeMode

DARK_QSS = """
QMainWindow, QWidget#centralWidget, QWidget#appDetailView {
    background-color: #18181f;
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

/* Typography & Labels */
QLabel {
    color: #e2e8f0;
}

QLabel#appTitleLabel {
    color: #f8fafc;
    font-size: 16px;
    font-weight: bold;
}

QLabel#appDescLabel {
    color: #94a3b8;
    font-size: 12px;
}

QLabel#formSectionMuted {
    color: #94a3b8;
    font-size: 11px;
}

/* Toolbar */
QToolBar {
    background-color: #20202a;
    border-bottom: 1px solid #2d2d38;
    padding: 6px 12px;
    spacing: 8px;
}

QToolBar QLabel {
    color: #cbd5e1;
}

QToolBar::separator {
    width: 1px;
    background-color: #2d2d38;
    margin: 4px 8px;
}

/* Tool Buttons */
QToolButton {
    background-color: #262633;
    color: #e2e8f0;
    border: 1px solid #363647;
    border-radius: 6px;
    padding: 5px 12px;
    font-weight: 500;
}
QToolButton:hover {
    background-color: #323244;
    border-color: #45455a;
    color: #ffffff;
}
QToolButton:pressed {
    background-color: #1c1c26;
}

/* Scroll Area & Viewport */
QScrollArea, QScrollArea > QWidget > QWidget {
    background-color: transparent;
    border: none;
}
QScrollArea::viewport {
    background-color: transparent;
}

/* Modern Scrollbars */
QScrollBar:vertical {
    background-color: #18181f;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background-color: #333342;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background-color: #4b4b5e;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    border: none;
    height: 0px;
}
QScrollBar:horizontal {
    background-color: #18181f;
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background-color: #333342;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #4b4b5e;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
    border: none;
    width: 0px;
}

/* Splitter */
QSplitter::handle {
    background-color: #2d2d38;
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
    color: #cbd5e1;
}
QListWidget#appSidebarList::item:selected {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QListWidget#appSidebarList::item:hover:!selected {
    background-color: #242430;
    color: #f1f5f9;
}

/* Group Boxes & Containers */
QGroupBox {
    background-color: #20202a;
    border: 1px solid #2e2e3d;
    border-radius: 8px;
    margin-top: 24px;
    padding: 16px 14px 14px 14px;
    font-weight: 600;
    color: #f3f4f6;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 3px 10px;
    color: #93c5fd;
    background-color: #20202a;
    border: 1px solid #2e2e3d;
    border-radius: 4px;
}

/* Inputs & Combos */
QLineEdit, QComboBox {
    background-color: #121217;
    border: 1px solid #3e3e4f;
    border-radius: 6px;
    padding: 7px 10px;
    color: #f3f4f6;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
}

QComboBox QAbstractItemView {
    background-color: #20202a;
    color: #f3f4f6;
    border: 1px solid #3e3e4f;
    border-radius: 6px;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}

/* Checkbox */
QCheckBox {
    color: #e2e8f0;
    font-weight: 500;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #3e3e4f;
    border-radius: 4px;
    background-color: #121217;
}
QCheckBox::indicator:hover {
    border-color: #3b82f6;
}
QCheckBox::indicator:checked {
    background-color: #2563eb;
    border-color: #3b82f6;
}

/* Buttons */
QPushButton {
    background-color: #262633;
    color: #e2e8f0;
    border: 1px solid #363647;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #323244;
    border-color: #45455a;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #1c1c26;
}

QPushButton#primaryActionBtn {
    background-color: #ea580c;
    color: #ffffff;
    border: 1px solid #c2410c;
    font-weight: 600;
    padding: 7px 16px;
}
QPushButton#primaryActionBtn:hover {
    background-color: #f97316;
    border-color: #ea580c;
}

QPushButton#fetchBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
    font-weight: 500;
}
QPushButton#fetchBtn:hover {
    background-color: #3b82f6;
    border-color: #2563eb;
}

/* Status Badges */
QLabel#statusBadgeRunning {
    color: #10b981;
    font-weight: 600;
}
QLabel#statusBadgeStopped {
    color: #94a3b8;
    font-weight: 600;
}
QLabel#statusBadgeTransitioning {
    color: #f59e0b;
    font-weight: 600;
}

/* Model Tag Chips */
QToolButton#modelChip {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 4px 10px;
    font-size: 11px;
    color: #93c5fd;
}
QToolButton#modelChip:hover {
    background-color: #2563eb;
    border-color: #3b82f6;
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
QMainWindow, QWidget#centralWidget, QWidget#appDetailView {
    background-color: #ffffff;
    color: #1e293b;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

/* Typography & Labels */
QLabel {
    color: #1e293b;
}

QLabel#appTitleLabel {
    color: #0f172a;
    font-size: 16px;
    font-weight: bold;
}

QLabel#appDescLabel {
    color: #64748b;
    font-size: 12px;
}

QLabel#formSectionMuted {
    color: #64748b;
    font-size: 11px;
}

/* Toolbar */
QToolBar {
    background-color: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
    padding: 6px 12px;
    spacing: 8px;
}

QToolBar QLabel {
    color: #475569;
}

QToolBar::separator {
    width: 1px;
    background-color: #e2e8f0;
    margin: 4px 8px;
}

/* Tool Buttons */
QToolButton {
    background-color: #ffffff;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 5px 12px;
    font-weight: 500;
}
QToolButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
    color: #0f172a;
}
QToolButton:pressed {
    background-color: #e2e8f0;
}

/* Scroll Area & Viewport */
QScrollArea, QScrollArea > QWidget > QWidget {
    background-color: transparent;
    border: none;
}
QScrollArea::viewport {
    background-color: transparent;
}

/* Modern Scrollbars */
QScrollBar:vertical {
    background-color: #ffffff;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background-color: #cbd5e1;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background-color: #94a3b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    border: none;
    height: 0px;
}
QScrollBar:horizontal {
    background-color: #ffffff;
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background-color: #cbd5e1;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #94a3b8;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
    border: none;
    width: 0px;
}

/* Splitter */
QSplitter::handle {
    background-color: #e2e8f0;
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
    color: #0f172a;
}

/* Group Boxes & Containers */
QGroupBox {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    margin-top: 24px;
    padding: 16px 14px 14px 14px;
    font-weight: 600;
    color: #1e293b;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 3px 10px;
    color: #1d4ed8;
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
}

/* Inputs & Combos */
QLineEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 7px 10px;
    color: #0f172a;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #2563eb;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}

/* Checkbox */
QCheckBox {
    color: #334155;
    font-weight: 500;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    background-color: #ffffff;
}
QCheckBox::indicator:hover {
    border-color: #2563eb;
}
QCheckBox::indicator:checked {
    background-color: #2563eb;
    border-color: #2563eb;
}

/* Buttons */
QPushButton {
    background-color: #ffffff;
    color: #334155;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
    color: #0f172a;
}
QPushButton:pressed {
    background-color: #e2e8f0;
}

QPushButton#primaryActionBtn {
    background-color: #ea580c;
    color: #ffffff;
    border: 1px solid #c2410c;
    font-weight: 600;
    padding: 7px 16px;
}
QPushButton#primaryActionBtn:hover {
    background-color: #f97316;
    border-color: #ea580c;
}

QPushButton#fetchBtn {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #1d4ed8;
    font-weight: 500;
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
    border-radius: 12px;
    padding: 4px 10px;
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
