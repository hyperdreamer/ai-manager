# Technical Specification: System Tray Support & Desktop Application Settings

## 1. Document Overview & Goals

This specification details the technical contracts, schemas, interfaces, error behavior, and test fixtures for:
1. **System Tray Integration** (`QSystemTrayIcon`) with left-click toggle, context menu (supervisor actions, settings, quit), and first-close educational balloon notification.
2. **Close-to-Tray vs. Clean Quit Semantics** with `QApplication.setQuitOnLastWindowClosed(False)` and unsaved draft state retention.
3. **Application Settings Dialog** (`SettingsDialog`) allowing configuration of:
   - Close window minimizes to system tray (`close_to_tray`)
   - Start minimized to system tray (`start_minimized`)
   - Run on system startup / autostart (`autostart`)
   - Desktop & Start Menu entry management (`ai-manager.desktop` in `~/.local/share/applications/`)
   - Appearance and polling preferences (live application without restart)
4. **Desktop Integration Service** (`DesktopIntegrationService`) managing FreeDesktop `.desktop` entries in `~/.config/autostart/` and `~/.local/share/applications/` with wrapper resolution (`/home/bin/ai-manager` / `start.sh`).
5. **CLI Runtime Overrides**: `--minimized` / `--tray` flags that override window visibility for the current execution without mutating persistent settings.

---

## 2. Configuration & State Schemas

### 2.1 `UserSettings` Model Extensions (`src/ai_manager/config/models.py`)

```python
class UserSettings(BaseModel):
    """Global user settings persisted in ~/.config/ai-manager/settings.json."""
    theme: ThemeMode = ThemeMode.DARK
    poll_interval_ms: int = 4000
    custom_presets: List[ProviderPreset] = Field(default_factory=list)
    # New Fields:
    close_to_tray: bool = True
    start_minimized: bool = False
    autostart: bool = False
    first_close_notice_shown: bool = False
```

- **Serialization**: JSON serialization via `settings.model_dump()` into `~/.config/ai-manager/settings.json`.
- **Backward Compatibility**: Missing fields in existing `settings.json` files instantiate with default values (`close_to_tray=True`, `start_minimized=False`, `autostart=False`, `first_close_notice_shown=False`).

---

## 3. Desktop Integration Service (`src/ai_manager/services/desktop_integration.py`)

A pure-Python service that interacts with the user's FreeDesktop directories (`~/.local/share/applications/` and `~/.config/autostart/`).

### 3.1 Paths & Constants
- `APP_DESKTOP_DIR`: `Path.home() / ".local" / "share" / "applications"`
- `AUTOSTART_DIR`: `Path.home() / ".config" / "autostart"`
- `DESKTOP_FILE_NAME`: `"ai-manager.desktop"`

### 3.2 Method Signatures & Contracts

```python
class DesktopIntegrationService:
    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root or find_ai_workspace_root()

    def get_launcher_command(self, start_minimized: bool = False) -> str:
        """Resolves the executable or wrapper script path with proper quoting.
        Priority:
        1. workspace_root / "start.sh" (if executable)
        2. shutil.which("ai-manager")
        3. sys.executable + " -m ai_manager.main"
        Appends ' --minimized' if start_minimized is True.
        """

    def generate_desktop_entry(self, start_minimized: bool = False) -> str:
        """Returns the FreeDesktop compliant .desktop file content:
        [Desktop Entry]
        Type=Application
        Name=ai-manager
        GenericName=AI Service Manager & Provider Configurator
        Comment=Configure AI models and supervise local AI backend services
        Exec=<launcher_command>
        Path=<workspace_root>
        Icon=utilities-system-monitor
        Terminal=false
        Categories=Development;Utility;Settings;
        StartupNotify=true
        StartupWMClass=ai-manager
        """

    def is_desktop_shortcut_installed(self) -> bool:
        """Returns True if ~/.local/share/applications/ai-manager.desktop exists and is readable."""

    def install_desktop_shortcut(self) -> bool:
        """Writes generate_desktop_entry(start_minimized=False) to APP_DESKTOP_DIR / DESKTOP_FILE_NAME.
        Ensures directory exists. Calls update-desktop-database APP_DESKTOP_DIR safely if available.
        Returns True on success.
        """

    def remove_desktop_shortcut(self) -> bool:
        """Removes APP_DESKTOP_DIR / DESKTOP_FILE_NAME if it exists.
        Returns True if removed or already absent.
        """

    def is_autostart_enabled(self) -> bool:
        """Returns True if ~/.config/autostart/ai-manager.desktop exists."""

    def set_autostart(self, enabled: bool, start_minimized: bool = False) -> bool:
        """If enabled is True:
           Writes generate_desktop_entry(start_minimized=start_minimized) to AUTOSTART_DIR / DESKTOP_FILE_NAME.
        If enabled is False:
           Removes AUTOSTART_DIR / DESKTOP_FILE_NAME.
        Returns True on success.
        """
```

---

## 4. System Tray Manager (`src/ai_manager/ui/system_tray.py`)

A Qt component wrapping `QSystemTrayIcon`.

### 4.1 Interface & Lifecycle

```python
class SystemTrayManager(QObject):
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

    def is_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        self._tray_icon.show()

    def hide(self) -> None:
        self._tray_icon.hide()

    def show_message(self, title: str, message: str, icon=QSystemTrayIcon.MessageIcon.Information, msecs: int = 5000) -> None:
        if self.is_available():
            self._tray_icon.showMessage(title, message, icon, msecs)

    def update_visibility_action_text(self, is_window_visible: bool) -> None:
        """Updates the text of the first menu item to 'Hide ai-manager' or 'Show ai-manager'."""
```

### 4.2 Tray Menu Structure
- `Action: Toggle Window ("Show ai-manager" / "Hide ai-manager")` -> triggers `toggle_window_requested`
- `Separator`
- `Action: "Start All Supervised Services"` -> triggers `start_all_services_requested`
- `Action: "Stop All Supervised Services"` -> triggers `stop_all_services_requested`
- `Separator`
- `Action: "⚙ Settings..."` -> triggers `open_settings_requested`
- `Separator`
- `Action: "Quit ai-manager"` -> triggers `quit_requested`

### 4.3 Activation Behavior
- Single click (`ActivationReason.Trigger`): emits `toggle_window_requested`.
- Context menu (`ActivationReason.Context`): displays context menu with refreshed toggle action text.

---

## 5. Application Settings Dialog (`src/ai_manager/ui/settings_dialog.py`)

A modal `QDialog` providing unified control over system integration, desktop shortcuts, and application preferences.

### 5.1 Interface & Signals

```python
class SettingsDialog(QDialog):
    settings_saved = pyqtSignal(UserSettings)

    def __init__(
        self,
        settings: UserSettings,
        desktop_service: DesktopIntegrationService,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.settings = settings.model_copy()
        self.desktop_service = desktop_service
        self._init_ui()
```

### 5.2 UI Layout & Interactions
1. **System Integration Group**:
   - `QCheckBox` (`chk_close_to_tray`): "Minimize to system tray when closing window [X]"
   - `QCheckBox` (`chk_start_minimized`): "Start minimized to system tray"
   - `QCheckBox` (`chk_autostart`): "Run on system startup (Autostart)"
2. **Desktop & Application Menu Group**:
   - `QLabel` (`lbl_desktop_status`): Displays styled badge "Installed in Application Menu" (Green) or "Not installed" (Neutral/Warning).
   - `QPushButton` (`btn_install_desktop`): "Install / Update Shortcut" -> calls `desktop_service.install_desktop_shortcut()` and updates badge.
   - `QPushButton` (`btn_remove_desktop`): "Remove Shortcut" -> calls `desktop_service.remove_desktop_shortcut()` and updates badge.
3. **General Preferences Group**:
   - Theme `QComboBox` (`cmb_theme`): "Dark" / "Light"
   - Polling Interval `QComboBox` (`cmb_poll`): 2000ms, 4000ms, 6000ms, 10000ms
4. **Dialog Buttons**:
   - `Cancel` (`QDialogButtonBox.StandardButton.Cancel`): closes without saving.
   - `Save & Apply` (`QDialogButtonBox.StandardButton.Save`):
     - Validates and updates `self.settings` object.
     - Synchronizes autostart status with `desktop_service.set_autostart(settings.autostart, start_minimized=settings.start_minimized)`.
     - Emits `settings_saved(new_settings)`.
     - Calls `self.accept()`.

---

## 6. Supervisor Service Controls Extension (`src/ai_manager/services/supervisor.py`)

To fulfill the tray actions (`Start All Supervised Services` / `Stop All Supervised Services`):
- `start_supervisor()`: Starts the supervisor daemon and all backends together via `ai-backends start`.
- `stop_supervisor()`: Stops all supervised backends and the supervisor daemon via `ai-backends stop`.

---

## 7. `MainWindow` & `main.py` Coordination

### 7.1 `main.py`
```python
def main():
    parser = argparse.ArgumentParser(description="ai-manager desktop administration")
    parser.add_argument("--minimized", "--tray", action="store_true", help="Start minimized to the system tray")
    args, unknown = parser.parse_known_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName("ai-manager")

    workspace = find_ai_workspace_root()
    window = MainWindow(workspace_root=workspace, start_minimized_override=args.minimized)

    if not window.is_minimized_at_startup:
        window.show()
    sys.exit(app.exec())
```

### 7.2 `MainWindow` Event Handling, Toolbar & Settings Wiring
- **Toolbar Addition**:
  - Add `[⚙ Settings]` `QToolButton` to the main window toolbar.
  - Connects to `self.open_settings_dialog()`.
- **Settings Dialog Integration**:
  - Opens `SettingsDialog(self.settings, self.desktop_service, parent=self)`.
  - Connects `settings_saved` to `self._on_settings_saved(new_settings)`.
  - In `_on_settings_saved`:
    - Updates `self.settings = new_settings` and saves to `settings.json`.
    - Updates `self._poll_timer.setInterval(new_settings.poll_interval_ms)`.
    - Calls `self._apply_theme(new_settings.theme)` for instant live application.
- **Window Activation/Toggle**:
  ```python
  def toggle_window_visibility(self):
      if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
          self.hide()
      else:
          # Unminimize and activate reliably on KDE Plasma / Wayland / X11
          self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
          self.showNormal()
          self.raise_()
          self.activateWindow()
  ```
- **Close Event**:
  ```python
  def closeEvent(self, event: QCloseEvent):
      if self._force_quit:
          event.accept()
          return

      if self.settings.close_to_tray and self.tray_manager.is_available():
          event.ignore()
          self.hide()
          if not self.settings.first_close_notice_shown:
              self.tray_manager.show_message(
                  "ai-manager running in tray",
                  "The application will keep supervising services in the background.\nClick the tray icon to restore or quit."
              )
              self.settings.first_close_notice_shown = True
              save_user_settings(self.settings)
      else:
          # Regular window close without tray
          if self.has_unsaved_changes():
              reply = QMessageBox.question(
                  self,
                  "Unsaved Changes",
                  "You have unsaved changes. Discard and exit?",
                  QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                  QMessageBox.StandardButton.Cancel,
              )
              if reply != QMessageBox.StandardButton.Discard:
                  event.ignore()
                  return
          event.accept()
  ```
- **Quit Action**:
  ```python
  def handle_quit(self):
      if self.has_unsaved_changes():
          self.showNormal()
          self.raise_()
          self.activateWindow()
          reply = QMessageBox.question(
              self,
              "Unsaved Changes",
              "You have unsaved changes. Discard and exit?",
              QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
              QMessageBox.StandardButton.Cancel,
          )
          if reply != QMessageBox.StandardButton.Discard:
              return
      self._force_quit = True
      self.close()
      QApplication.instance().quit()
  ```

---

## 8. Test Strategy & Verification Fixtures

1. **Test Fixtures & Headless Isolation**:
   - Provide `mock_tray_available` in `conftest.py` that monkeypatches `QSystemTrayIcon.isSystemTrayAvailable` to return `True` without requiring a physical DBus notification daemon.
   - Use `qtbot.waitUntil` and `qtbot.wait_exposed` for reliable PyQt6 UI state assertions.
2. **`tests/test_desktop_integration.py`**:
   - `test_generate_desktop_entry`: Verify generated text conforms to INI FreeDesktop specifications, contains valid quoted Exec path, `Path=` key, and `--minimized` when requested.
   - `test_install_and_remove_desktop_shortcut`: Use mock `APP_DESKTOP_DIR` in `tmp_path` to test atomic file writes, permissions, and clean deletion.
   - `test_autostart_toggle`: Test writing and removing autostart desktop entry in isolated temp path.
3. **`tests/test_user_settings.py`**:
   - Test default values for new fields (`close_to_tray`, `start_minimized`, `autostart`, `first_close_notice_shown`).
   - Test roundtrip serialization to and from JSON.
4. **`tests/test_system_tray.py`**:
   - Test signals emitted on menu action triggers and single click activation.
   - Test `update_visibility_action_text` sets appropriate text.
5. **`tests/test_main_window_tray.py`**:
   - Test `closeEvent` ignores event and hides window when `close_to_tray=True`.
   - Test `closeEvent` accepts when `_force_quit=True`.
   - Test `toggle_window_visibility` unminimizes and restores window state.
   - Test `open_settings_dialog` and live settings synchronization.
