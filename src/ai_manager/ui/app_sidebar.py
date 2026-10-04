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
        item.setText(f"{title}\n   Port {meta.default_port}")

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
