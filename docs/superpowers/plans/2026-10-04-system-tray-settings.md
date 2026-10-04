# Implementation Plan: System Tray Support & Desktop Application Settings

This plan describes the discrete tasks required to implement system tray support (including close-to-tray), application settings dialog, desktop entry shortcut management, autostart integration, and supervisor batch controls.

## Global Constraints
- Python 3.10+ and PyQt6.
- Strict test-driven development (write tests in `tests/`, implement feature code in `src/ai_manager/`).
- Use `pytest` for running test suites.
- Do not introduce external dependencies beyond existing project dependencies (`PyQt6`, `pydantic`, `pytest`, `pytest-qt`).
- All file paths in tasks are repository-relative.

---

## Task 1: Extend UserSettings Model and Tests
**Implementer tier:** frontier

Extend `UserSettings` in `src/ai_manager/config/models.py` with the new configuration fields and default values, and add serialization unit tests.

### Files:
- `src/ai_manager/config/models.py`
- `tests/test_user_settings.py`

### Interfaces:
- In `src/ai_manager/config/models.py`:
  ```python
  class UserSettings(BaseModel):
      theme: ThemeMode = ThemeMode.DARK
      poll_interval_ms: int = 4000
      custom_presets: List[ProviderPreset] = Field(default_factory=list)
      close_to_tray: bool = True
      start_minimized: bool = False
      autostart: bool = False
      first_close_notice_shown: bool = False
  ```

### Checklist:
- [ ] Add unit tests in `tests/test_user_settings.py` verifying default values for `close_to_tray`, `start_minimized`, `autostart`, and `first_close_notice_shown`.
- [ ] Verify serialization and deserialization via `UserSettings(**data)` and `settings.model_dump()`.
- [ ] Update `UserSettings` in `src/ai_manager/config/models.py`.
- [ ] Run `pytest tests/test_user_settings.py` and confirm all tests pass.

### Commit Instructions:
```bash
git add src/ai_manager/config/models.py tests/test_user_settings.py
git commit -m "feat(config): extend UserSettings with tray and autostart fields"
```

---

## Task 2: Implement DesktopIntegrationService and Tests
**Implementer tier:** frontier

Implement `DesktopIntegrationService` in `src/ai_manager/services/desktop_integration.py` for generating, installing, and removing `.desktop` files in `~/.local/share/applications` and `~/.config/autostart`.

### Files:
- `src/ai_manager/services/desktop_integration.py`
- `tests/test_desktop_integration.py`

### Interfaces:
- `DesktopIntegrationService(workspace_root: Optional[Path] = None)`:
  - `get_launcher_command(start_minimized: bool = False) -> str`
  - `generate_desktop_entry(start_minimized: bool = False) -> str`
  - `is_desktop_shortcut_installed() -> bool`
  - `install_desktop_shortcut() -> bool`
  - `remove_desktop_shortcut() -> bool`
  - `is_autostart_enabled() -> bool`
  - `set_autostart(enabled: bool, start_minimized: bool = False) -> bool`

### Checklist:
- [ ] Write unit tests in `tests/test_desktop_integration.py` with mock directories (`tmp_path`) for application and autostart directories.
- [ ] Test `generate_desktop_entry` with and without `--minimized`, verifying `Exec=`, `Path=`, and standard FreeDesktop keys.
- [ ] Test `install_desktop_shortcut`, `remove_desktop_shortcut`, `is_desktop_shortcut_installed`.
- [ ] Test `set_autostart` enabling and disabling autostart file.
- [ ] Implement `DesktopIntegrationService` in `src/ai_manager/services/desktop_integration.py`.
- [ ] Run `pytest tests/test_desktop_integration.py` and ensure 100% pass.

### Commit Instructions:
```bash
git add src/ai_manager/services/desktop_integration.py tests/test_desktop_integration.py
git commit -m "feat(services): implement DesktopIntegrationService for shortcut and autostart management"
```

---

## Task 3: SupervisorManager Batch Service Controls
**Implementer tier:** frontier

Extend `SupervisorManager` in `src/ai_manager/services/supervisor.py` with `stop_supervisor()` to complement `start_supervisor()`, enabling tray menu batch start/stop actions.

### Files:
- `src/ai_manager/services/supervisor.py`
- `tests/test_supervisor.py`

### Interfaces:
- In `SupervisorManager`:
  - `stop_supervisor() -> None`: Invokes `ai-backends stop` using `QProcess` in the same manner as `start_supervisor()`.

### Checklist:
- [ ] Add unit test in `tests/test_supervisor.py` testing `stop_supervisor()` process execution and signal dispatch.
- [ ] Implement `stop_supervisor()` in `SupervisorManager`.
- [ ] Run `pytest tests/test_supervisor.py` and verify all tests pass.

### Commit Instructions:
```bash
git add src/ai_manager/services/supervisor.py tests/test_supervisor.py
git commit -m "feat(supervisor): add stop_supervisor command"
```

---

## Task 4: Implement SystemTrayManager Component and Tests
**Implementer tier:** frontier

Implement `SystemTrayManager` wrapping `QSystemTrayIcon` with left-click toggle, context menu, and balloon notification support.

### Files:
- `src/ai_manager/ui/system_tray.py`
- `tests/test_system_tray.py`

### Interfaces:
- `SystemTrayManager(parent: Optional[QWidget] = None)`:
  - Signals: `toggle_window_requested`, `show_window_requested`, `hide_window_requested`, `open_settings_requested`, `start_all_services_requested`, `stop_all_services_requested`, `quit_requested`
  - Methods: `is_available() -> bool`, `show()`, `hide()`, `show_message(title, message, icon, msecs)`, `update_visibility_action_text(is_window_visible: bool)`

### Checklist:
- [ ] Write unit tests in `tests/test_system_tray.py` testing signal emissions when actions are triggered and dynamic visibility text updates.
- [ ] Implement `SystemTrayManager` in `src/ai_manager/ui/system_tray.py`.
- [ ] Verify menu actions structure: Toggle, Start All, Stop All, Settings, Quit.
- [ ] Run `pytest tests/test_system_tray.py` and verify pass.

### Commit Instructions:
```bash
git add src/ai_manager/ui/system_tray.py tests/test_system_tray.py
git commit -m "feat(ui): implement SystemTrayManager component"
```

---

## Task 5: Implement SettingsDialog Component and Tests
**Implementer tier:** frontier

Implement the modal `SettingsDialog` in `src/ai_manager/ui/settings_dialog.py` for configuring system integration, shortcut installation, and application preferences.

### Files:
- `src/ai_manager/ui/settings_dialog.py`
- `tests/test_settings_dialog.py`

### Interfaces:
- `SettingsDialog(settings: UserSettings, desktop_service: DesktopIntegrationService, parent: Optional[QWidget] = None)`:
  - Signal: `settings_saved = pyqtSignal(UserSettings)`
  - Controls:
    - `chk_close_to_tray`, `chk_start_minimized`, `chk_autostart`
    - `lbl_desktop_status`, `btn_install_desktop`, `btn_remove_desktop`
    - `cmb_theme`, `cmb_poll_interval`
    - `btn_save`, `btn_cancel`

### Checklist:
- [ ] Write unit tests in `tests/test_settings_dialog.py` testing initial control states from `UserSettings`, toggling autostart, installing desktop shortcut, and emitting `settings_saved`.
- [ ] Implement `SettingsDialog` with dark/light theme styling matching the design mockup.
- [ ] Connect `btn_save` to synchronize autostart via `desktop_service.set_autostart(settings.autostart, start_minimized=settings.start_minimized)`.
- [ ] Run `pytest tests/test_settings_dialog.py` and verify pass.

### Commit Instructions:
```bash
git add src/ai_manager/ui/settings_dialog.py tests/test_settings_dialog.py
git commit -m "feat(ui): implement SettingsDialog component"
```

---

## Task 6: Integrate System Tray and Settings into MainWindow
**Implementer tier:** frontier

Integrate `SystemTrayManager`, `SettingsDialog`, and `DesktopIntegrationService` into `MainWindow`, including toolbar action, close-to-tray handling, live preference updates, and clean application exit.

### Files:
- `src/ai_manager/ui/main_window.py`
- `tests/test_main_window_tray.py`

### Interfaces:
- In `MainWindow`:
  - `self.tray_manager: SystemTrayManager`
  - `self.desktop_service: DesktopIntegrationService`
  - `open_settings_dialog()`
  - `_on_settings_saved(new_settings: UserSettings)`
  - `toggle_window_visibility()`
  - `handle_quit()`
  - `closeEvent(event: QCloseEvent)`: intercepts close to minimize to tray when `close_to_tray` is enabled.

### Checklist:
- [ ] Write integration tests in `tests/test_main_window_tray.py`:
  - Test toolbar contains Settings button that triggers `open_settings_dialog()`.
  - Test `closeEvent` ignores close and hides window when `close_to_tray` is True.
  - Test `closeEvent` accepts when `_force_quit` is True.
  - Test `handle_quit` checks for unsaved changes before exiting.
  - Test `_on_settings_saved` updates live theme and poll interval.
- [ ] Implement integration in `src/ai_manager/ui/main_window.py`.
- [ ] Run `pytest tests/test_main_window_tray.py` and verify all tests pass.

### Commit Instructions:
```bash
git add src/ai_manager/ui/main_window.py tests/test_main_window_tray.py
git commit -m "feat(ui): integrate system tray, settings dialog, and close-to-tray in MainWindow"
```

---

## Task 7: CLI Arguments and Startup Integration in main.py
**Implementer tier:** frontier

Update `src/ai_manager/main.py` with CLI argument parsing (`--minimized` / `--tray`), `setQuitOnLastWindowClosed(False)`, `setDesktopFileName("ai-manager")`, and start-minimized handling.

### Files:
- `src/ai_manager/main.py`
- `tests/test_main_cli.py`

### Interfaces:
- In `src/ai_manager/main.py`:
  - CLI flags: `--minimized`, `--tray`
  - `app.setQuitOnLastWindowClosed(False)`
  - `app.setDesktopFileName("ai-manager")`

### Checklist:
- [ ] Write CLI tests in `tests/test_main_cli.py` verifying `--minimized` and `--tray` arguments are parsed correctly.
- [ ] Update `main.py` to parse arguments and initialize `MainWindow` with `start_minimized_override`.
- [ ] Run the complete test suite: `pytest tests/` and verify 100% passing tests.

### Commit Instructions:
```bash
git add src/ai_manager/main.py tests/test_main_cli.py
git commit -m "feat(app): add CLI arguments for start-minimized and configure desktop metadata"
```
