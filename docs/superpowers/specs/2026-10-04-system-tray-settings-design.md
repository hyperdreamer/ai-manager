# Design Document: System Tray Support & Desktop Application Settings

## 1. Background & Goals

`ai-manager` is a PyQt6 desktop control center that configures AI API credentials and models across a suite of local AI services, while supervising their execution lifecycle. Currently, closing the window terminates the application process. Users want continuous background execution and native desktop integration:

1. **System Tray Integration**:
   - The application can minimize to the system tray on window close instead of terminating.
   - A tray icon resides in the system notification area (e.g. KDE Plasma / GNOME / XFCE / Wayland / X11 tray).
   - Left-clicking the tray icon toggles window visibility (restores and brings to front, or minimizes to tray).
   - Right-clicking opens a context menu with actions to show/hide, control supervisor services, open Settings, and quit.
   - On first close to tray, display a transient tray notification explaining that the app continues running in the background.

2. **Application Settings Dialog**:
   - Accessible via a dedicated `[⚙ Settings]` button on the main toolbar as well as from the tray context menu.
   - Allows users to configure:
     - **Close to tray**: Whether clicking `[X]` hides to system tray or exits the app (default: enabled).
     - **Start minimized**: Whether launching the app starts hidden in the tray without showing the main window (default: disabled).
     - **Run on system startup**: Autostart on user login (default: disabled).
     - **Add/Install Desktop Entry**: Install or remove `ai-manager.desktop` directly into `~/.local/share/applications/` so it appears in the Plasma Application Menu / KRunner without manual shell scripts.
     - **Theme & Polling preferences**: Consolidated view of existing settings (Theme Dark/Light, supervisor status polling interval).

3. **CLI Arguments**:
   - Support `--minimized` / `--tray` CLI argument so the autostart entry or terminal execution can launch the app directly into tray-only mode.

---

## 2. Architecture & Components

### 2.1 Configuration Schema Extensions (`UserSettings`)
Located in `src/ai_manager/config/models.py`:
- `close_to_tray: bool = True`: When `True`, `closeEvent` on `MainWindow` minimizes/hides the window instead of exiting.
- `start_minimized: bool = False`: When `True` (or when `--minimized`/`--tray` is passed via CLI), the main window remains hidden at startup while the tray icon is active.
- `autostart: bool = False`: Controls presence of `~/.config/autostart/ai-manager.desktop`.
- `first_close_notice_shown: bool = False`: Tracks whether the introductory "app is still running in tray" notification has been displayed.

### 2.1.1 Application Lifecycle & Quit Handling
- **`QApplication.setQuitOnLastWindowClosed(False)`**: Configured in `main.py` so closing/hiding `MainWindow` does not cause Qt to terminate the application event loop while the tray icon is active.
- **Unsaved Changes vs. Close-to-Tray**:
  - Closing `MainWindow` to tray (`close_to_tray=True`) simply hides the window; unsaved in-memory draft configurations are retained without prompting to "Discard and exit?".
  - True Application Exit (via Tray Context Menu -> "Quit ai-manager" or toolbar action): Prompts the user if unsaved draft changes exist. If cancelled, the quit operation is aborted.
- **CLI Flags as Runtime Overrides**:
  - `--minimized` / `--tray` are session-only overrides (starting the app with window hidden) and do NOT overwrite the persisted `start_minimized` boolean in `settings.json`.
- **Desktop File Executable & Environment Resolution**:
  - `.desktop` files point to the launcher wrapper `/home/bin/ai-manager` (or `start.sh`) to preserve necessary environment flags (`QT_XCB_GL_INTEGRATION=none`) and Conda environment activation.
- **Wayland / KDE Plasma Desktop Entry Binding**:
  - Call `app.setDesktopFileName("ai-manager")` in `main.py` so Wayland compositors bind the running window to the `.desktop` file for taskbar grouping and tray association.
- **Window Activation**:
  - Restoring `MainWindow` from the system tray calls `window.showNormal()`, `window.raise_()`, and `window.activateWindow()` to guarantee the window is brought to the foreground in KDE Plasma.

### 2.2 System Integration Service (`DesktopIntegrationService`)
A new dedicated module `src/ai_manager/services/desktop_integration.py` responsible for managing Linux desktop entries:
- **Paths**:
  - Applications Menu entry: `~/.local/share/applications/ai-manager.desktop`
  - Autostart entry: `~/.config/autostart/ai-manager.desktop`
- **Resolution**:
  - Executable path: Resolves `sys.executable` and the appropriate execution arguments (e.g. `python -m ai_manager.main` or direct console script executable `ai-manager`).
  - Working directory / Workspace root: `Path(__file__).resolve()...` or workspace root locator.
  - Icon: Path to an application SVG/PNG icon in resources (with standard fallback icon name `utilities-system-monitor` or `applications-system`).
- **Methods**:
  - `generate_desktop_entry(start_minimized: bool = False) -> str`: Renders valid FreeDesktop `.desktop` content.
  - `is_desktop_shortcut_installed() -> bool`: Checks existence and validity of `~/.local/share/applications/ai-manager.desktop`.
  - `install_desktop_shortcut() -> bool`: Writes entry and invokes `update-desktop-database` if present.
  - `remove_desktop_shortcut() -> bool`: Deletes entry.
  - `is_autostart_enabled() -> bool`: Checks existence of `~/.config/autostart/ai-manager.desktop`.
  - `set_autostart(enabled: bool, start_minimized: bool = False) -> bool`: Creates or removes the autostart `.desktop` file.

### 2.3 System Tray Manager (`SystemTrayManager`)
Located in `src/ai_manager/ui/system_tray.py`:
- Wraps `QSystemTrayIcon`.
- Provides icon setup with high-DPI and dark/light theme awareness (or standard icon fallback).
- Signal handling:
  - `activated(QSystemTrayIcon.ActivationReason)`: On `Trigger` (single left click), toggles `MainWindow` visibility.
- Context menu:
  - `Show / Hide ai-manager` (dynamic text based on window visibility).
  - Separator.
  - `Start All Services` (triggers `supervisor_manager.start_all()`).
  - `Stop All Services` (triggers `supervisor_manager.stop_all()`).
  - Separator.
  - `Settings...` (opens `SettingsDialog`).
  - Separator.
  - `Quit ai-manager` (triggers explicit full application exit: `QApplication.quit()`).
- Balloon / Notification helper:
  - `show_message(title, message, icon)` for user feedback.

### 2.4 Settings Dialog (`SettingsDialog`)
Located in `src/ai_manager/ui/settings_dialog.py`:
- Modal `QDialog` styled with application theme (`theme.py`).
- **Sections**:
  - **System Integration**:
    - Checkbox: "Minimize to system tray when closing window"
    - Checkbox: "Start minimized to system tray"
    - Checkbox: "Run on system startup"
  - **Application Menu**:
    - Status label: "Status: Installed in Application Menu" / "Not installed"
    - Action buttons: `[Install / Update Shortcut]` and `[Remove Shortcut]`
  - **General Preferences**:
    - Theme combo box (Dark / Light)
    - Polling interval spin box / combo (2000ms, 4000ms, 6000ms, etc.)
- Saves updated `UserSettings` to `~/.config/ai-manager/settings.json` upon clicking `[Save & Apply]`.
- Synchronizes autostart desktop entry whenever the autostart setting changes.

### 2.5 `MainWindow` & `main.py` Integration
- `main.py`: Parses CLI options (`--minimized`, `--tray`).
  - If `settings.start_minimized` or `--minimized` or `--tray` is set, `window.show()` is NOT called; only the tray icon is shown.
- `MainWindow`:
  - Instantiates `SystemTrayManager` and `DesktopIntegrationService`.
  - Overrides `closeEvent(event: QCloseEvent)`:
    - If `self.settings.close_to_tray` and `self.tray_manager.is_available()`:
      - `event.ignore()`
      - `self.hide()`
      - If not `self.settings.first_close_notice_shown`:
        - Displays tray message: "ai-manager is still running in the system tray."
        - Updates `self.settings.first_close_notice_shown = True` and saves settings.
    - Else:
      - `event.accept()`
  - Adds `[⚙ Settings]` button to the top toolbar to launch `SettingsDialog`.

---

## 3. UI Visual Mockup

### Settings Dialog
```text
+--------------------------------------------------------------------------+
|  Application Settings                                              [X]   |
+--------------------------------------------------------------------------+
|                                                                          |
|  System Integration                                                      |
|  ----------------------------------------------------------------------  |
|  [✓] Close window minimizes to system tray                               |
|  [ ] Start minimized to system tray                                      |
|  [ ] Run on system startup (Autostart)                                   |
|      Creates ~/.config/autostart/ai-manager.desktop                      |
|                                                                          |
|  Desktop Shortcut & Start Menu                                           |
|  ----------------------------------------------------------------------  |
|  Status: [ Installed in Application Menu ✓ ]                             |
|  [ Install / Update Desktop Shortcut ]   [ Remove Desktop Shortcut ]     |
|                                                                          |
|  General Preferences                                                     |
|  ----------------------------------------------------------------------  |
|  Theme:             [ Dark        ▾ ]                                    |
|  Polling Interval:  [ 4000 ms     ▾ ]  (Status refresh frequency)        |
|                                                                          |
+--------------------------------------------------------------------------+
|                                              [ Cancel ]    [ Save & Apply ] |
+--------------------------------------------------------------------------+
```

### System Tray Context Menu
```text
+-------------------------------------+
|  Show ai-manager                    |
|  ---------------------------------  |
|  Start All Supervised Services      |
|  Stop All Supervised Services       |
|  ---------------------------------  |
|  ⚙ Settings...                      |
|  ---------------------------------  |
|  Quit ai-manager                    |
+-------------------------------------+
```

---

## 4. Error Handling & Edge Cases

1. **System Tray Unavailable**:
   - If `QSystemTrayIcon.isSystemTrayAvailable()` returns `False` (e.g. headless or minimal window manager without StatusNotifierItem/tray support):
     - `closeEvent` must fall back to normal exit (`event.accept()`) so the application is not trapped in an invisible running state.
     - The Settings dialog indicates that the system tray is unavailable on the current display server.
2. **Desktop Directory Missing**:
   - Ensure `~/.config/autostart` and `~/.local/share/applications` directories are created with `mkdir(parents=True, exist_ok=True)` before file creation.
3. **Execution Command Path in Desktop File**:
   - Prefer absolute path to virtualenv / binary if available (e.g. `shutil.which("ai-manager")` or `sys.executable -m ai_manager.main`).
   - If launched in a virtualenv or development environment, properly quote paths and include `--minimized` for autostart.
4. **Clean Exit**:
   - When "Quit" is clicked in the tray menu or main window, set a private flag `self._force_quit = True` before calling `QApplication.quit()` or `window.close()`, guaranteeing `closeEvent` does not intercept and cancel the shutdown.

---

## 5. Testing & Verification Strategy

1. **Unit Tests**:
   - Test `DesktopIntegrationService`:
     - Test generating valid `.desktop` content (valid syntax, Exec line with and without `--minimized`).
     - Test installation and removal using temporary directories (`tmp_path`).
   - Test `UserSettings` serialization:
     - Verify new fields load/save with proper defaults.
2. **Integration / UI Tests (PyQt6 / pytest-qt)**:
   - Test `MainWindow` close event handling:
     - When `close_to_tray` is `True`, verify `closeEvent` ignores the event and window hides.
     - When `_force_quit` is set, verify `closeEvent` accepts.
   - Test CLI argument parsing:
     - Test `--minimized` starts with `window.isVisible() == False`.
   - Test `SettingsDialog` state synchronization:
     - Toggling options updates `UserSettings` and invokes `DesktopIntegrationService`.
