from typing import Dict, Optional
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from ai_manager.config.models import AppMetadata, ServiceRunState, ServiceStatus


class AppSidebar(QWidget):
    """Sidebar widget listing applications with status and dirty indicators."""

    app_selected = pyqtSignal(str)

    def __init__(self, apps: Dict[str, AppMetadata], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.apps = apps
        self._dirty_apps = set()
        self._statuses: Dict[str, ServiceStatus] = {}
        # Last successfully loaded/committed port per app. A missing entry means
        # "no readable saved port", so the metadata default is displayed.
        self._configured_ports: Dict[str, int] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._list_widget = QListWidget(self)
        self._list_widget.setObjectName("appSidebarList")
        self._list_widget.itemSelectionChanged.connect(self._on_selection_changed)

        layout.addWidget(self._list_widget)
        self._init_items()

    def _init_items(self) -> None:
        for app_id, meta in self.apps.items():
            item = QListWidgetItem(self._list_widget)
            item.setData(Qt.ItemDataRole.UserRole, app_id)
            self._update_item_text(item, app_id)
            self._list_widget.addItem(item)

        if self._list_widget.count() > 0:
            self._list_widget.setCurrentRow(0)

    def _update_item_text(self, item: QListWidgetItem, app_id: str) -> None:
        meta = self.apps[app_id]
        status = self._statuses.get(app_id)
        dot = "●" if status and status.state == ServiceRunState.RUNNING else "○"
        dirty = "*" if app_id in self._dirty_apps else ""

        title = f"{dot} {meta.display_name}{dirty}"
        port = self._configured_ports.get(app_id, meta.default_port)
        item.setText(f"{title}\n   Port {port}")

    def update_configured_port(self, app_id: str, port: int | None) -> None:
        """Cache and display the effective configured port for ``app_id``.

        ``None`` forgets the saved port so the metadata default is shown again.
        Booleans are rejected even though ``bool`` is an ``int`` subclass.
        """
        if app_id not in self.apps:
            raise KeyError(app_id)
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):
            raise ValueError("Configured port must be an integer from 1 to 65535.")
        if port is None:
            self._configured_ports.pop(app_id, None)
        else:
            self._configured_ports[app_id] = port
        for index in range(self._list_widget.count()):
            item = self._list_widget.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == app_id:
                self._update_item_text(item, app_id)
                break

    def update_status(self, app_id: str, status: ServiceStatus) -> None:
        self._statuses[app_id] = status
        for idx in range(self._list_widget.count()):
            item = self._list_widget.item(idx)
            if item.data(Qt.ItemDataRole.UserRole) == app_id:
                self._update_item_text(item, app_id)
                break

    def set_dirty(self, app_id: str, is_dirty: bool) -> None:
        if is_dirty:
            self._dirty_apps.add(app_id)
        else:
            self._dirty_apps.discard(app_id)

        for idx in range(self._list_widget.count()):
            item = self._list_widget.item(idx)
            if item.data(Qt.ItemDataRole.UserRole) == app_id:
                self._update_item_text(item, app_id)
                break

    def current_app_id(self) -> Optional[str]:
        item = self._list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def select_app(self, app_id: str) -> None:
        for idx in range(self._list_widget.count()):
            item = self._list_widget.item(idx)
            if item.data(Qt.ItemDataRole.UserRole) == app_id:
                self._list_widget.setCurrentRow(idx)
                break

    def _on_selection_changed(self) -> None:
        app_id = self.current_app_id()
        if app_id:
            self.app_selected.emit(app_id)
