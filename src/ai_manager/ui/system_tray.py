"""System tray integration for ai-manager.

``SystemTrayManager`` wraps a :class:`QSystemTrayIcon` and translates tray
interactions into higher-level signals consumed by ``MainWindow``. It never
caches tray availability so callers always observe the current display
server state.
"""

from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QMenu,
    QStyle,
    QSystemTrayIcon,
    QWidget,
)

from ai_manager.ui.icons import tray_icon


class SystemTrayManager(QObject):
    """Owns the tray icon, its context menu and activation behaviour."""

    # Reserved for future distinct show/hide requests. The context menu and
    # single-click activation currently funnel through
    # ``toggle_window_requested`` because the tray exposes one dynamic
    # Show/Hide item; these signals are kept to preserve the documented
    # interface for consumers that need to distinguish the two intents later.
    show_window_requested = pyqtSignal()
    hide_window_requested = pyqtSignal()
    toggle_window_requested = pyqtSignal()
    open_settings_requested = pyqtSignal()
    start_all_services_requested = pyqtSignal()
    stop_all_services_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._tray_icon = QSystemTrayIcon(parent)
        self._context_menu = QMenu(parent)
        self._init_ui()
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._on_palette_changed)

    def _init_ui(self) -> None:
        self._apply_icon()

        self._toggle_action = self._context_menu.addAction("Show ai-manager")
        self._toggle_action.triggered.connect(self.toggle_window_requested.emit)

        self._context_menu.addSeparator()

        self._start_all_action = self._context_menu.addAction(
            "Start All Supervised Services"
        )
        self._start_all_action.triggered.connect(
            self.start_all_services_requested.emit
        )

        self._stop_all_action = self._context_menu.addAction(
            "Stop All Supervised Services"
        )
        self._stop_all_action.triggered.connect(
            self.stop_all_services_requested.emit
        )

        self._context_menu.addSeparator()

        self._settings_action = self._context_menu.addAction("⚙ Settings...")
        self._settings_action.triggered.connect(self.open_settings_requested.emit)

        self._context_menu.addSeparator()

        self._quit_action = self._context_menu.addAction("Quit ai-manager")
        self._quit_action.triggered.connect(self.quit_requested.emit)

        self._tray_icon.setContextMenu(self._context_menu)
        self._tray_icon.activated.connect(self._on_activated)

    def _apply_icon(self) -> None:
        """Apply the palette-tinted symbolic icon with a standard fallback."""
        app = QApplication.instance()
        if app is None:
            return
        icon = tray_icon(app)
        if icon.isNull():
            icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self._tray_icon.setIcon(icon)

    def _on_palette_changed(self, palette: QPalette | None = None) -> None:
        """Re-tint the tray icon when the application palette changes."""
        self._apply_icon()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_window_requested.emit()

    def is_available(self) -> bool:
        """Return whether a system tray is available right now (never cached)."""
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        """Show the tray icon."""
        self._tray_icon.show()

    def hide(self) -> None:
        """Hide the tray icon."""
        self._tray_icon.hide()

    def show_message(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        msecs: int = 5000,
    ) -> None:
        """Display a transient tray notification when a tray is available."""
        if self.is_available():
            self._tray_icon.showMessage(title, message, icon, msecs)

    def update_visibility_action_text(self, is_window_visible: bool) -> None:
        """Reflect the current window visibility in the toggle menu item."""
        self._toggle_action.setText(
            "Hide ai-manager" if is_window_visible else "Show ai-manager"
        )
