# App Version Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the deterministic
> subagent-driven-development controller to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax; leave them unticked during execution.

**Goal:** Display the existing application version in the main title and a compact About dialog reachable from the tray and Settings, with packaging derived from the single source literal.

**Architecture:** A new leaf `AboutDialog` imports the version and existing icon helper, owns only presentation, and resolves its optional version inside its constructor. MainWindow handles the tray signal, while Settings opens its own parented About dialog from a separate footer button. Setuptools reads the unchanged literal statically; pytest pins source structure, UI propagation, entry-point behavior, and release documentation.

**Tech Stack:** Python standard library, existing PyQt6, pytest, pytest-qt, and setuptools; existing headless Qt fixtures.

**File structure:**

- `src/ai_manager/ui/about_dialog.py` and `tests/test_about_dialog.py`: leaf dialog, sizing, ownership, content, icon provenance, and Close behavior (Task 1).
- `src/ai_manager/ui/system_tray.py`, `src/ai_manager/ui/main_window.py`, and their existing test modules: tray action/signal, title, and MainWindow entry point (Task 2).
- `src/ai_manager/ui/settings_dialog.py` and its existing test module: About/stretch/button box footer and Settings-owned modal entry point (Task 3).
- `pyproject.toml`, `tests/test_version.py`, `README.md`, and `tests/test_readme_documents_version.py`: derived packaging metadata, static version guards, and tested release documentation (Task 4).

## Global Constraints

- Single-literal version rule: the sole authored application-version source is the unchanged module-level `__version__ = "0.1.3"` in `src/ai_manager/__init__.py`, represented by one `ast.Assign` with a string `ast.Constant`; documentation, injected test data, and derived metadata are not independent sources.
- Release-triplet scheme: the current application version matches exactly `^\d+\.\d+\.\d+$`; retain `0.1.3`, import the symbol in current-version assertions, and render supplied values unchanged, including injected pre-release test data.
- Add no new runtime or dev dependencies; preserve the existing build backend, dependency declarations, optional dependencies, script, and package data.
- Use PyQt6 + pytest-qt only for new GUI behavior and Qt tests, together with pytest and the Python standard library; reuse the existing headless fixtures in `tests/conftest.py` unchanged.
- The exact full-suite command, from the implementation worktree root, is `AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src pytest tests/`; require exit status 0 and no failures.
- Packaging author metadata must be exactly `[{ name = "Henry", email = "wenhepku@gmail.com" }]`; the author email is `wenhepku@gmail.com`.
- A `--version` CLI flag and git provenance are prohibited; add no commit suffix, date stamp, dirty-tree detection, or git subprocess.
- All existing tests must keep passing; retain every existing assertion outside the three explicitly updated tray tests, including Save, Cancel, availability, and mnemonic non-vacuity assertions.
- Runtime version reads are `from ai_manager import __version__`, with no IO, metadata lookup, subprocess, validation, normalization, exception path, or fallback; neither consumer imports `importlib`, `importlib.metadata`, `subprocess`, `platform`, or `tomllib` or contains a version literal.
- Leave `src/ai_manager/__init__.py`, `src/ai_manager/ui/icons.py`, `src/ai_manager/ui/mnemonic.py`, `tests/test_mnemonic.py`, and `tests/conftest.py` unchanged; add no service, persisted state, settings key, asset, telemetry, update checking, license/credits pane, or tray-tooltip version.
- Both About entry points create a fresh dialog on every invocation and call its `exec()` once; factory mocks prove constructor calls, while tests patching only the real class's `exec` prove ownership and side-effect freedom.
- The approved contracts are `docs/superpowers/specs/2026-10-20-app-version-display-spec.md` and `docs/superpowers/specs/2026-10-20-app-version-display-design.md`; the specification's resolved Settings footer supersedes ActionRole placement.
- Line ranges below refer to baseline `4cd30cd`; locate the named enclosing member if preceding tasks shift lines, without broad refactoring.
- Task 4 contains the plan's single non-pytest verification: the exact wheel build and exact-wheel METADATA inspection together, after the full pytest suite passes; commit commands are task handoffs, not additional verification gates.

## Task 1: Build and test the leaf About dialog

**Implementer tier:** Economy

**Files:**

- Create: `src/ai_manager/ui/about_dialog.py`
- Create: `tests/test_about_dialog.py`
- Read only: `src/ai_manager/__init__.py:1-3`
- Read only: `src/ai_manager/ui/icons.py:100-108`
- Read only: `tests/test_mnemonic.py:141-162`
- Read only: `tests/conftest.py:1-95`

**Interfaces:**

- Consumes existing `ai_manager.__version__: str` via `from ai_manager import __version__` and `ai_manager.ui.icons.color_icon() -> QIcon` via a module-scope `from ai_manager.ui.icons import color_icon`.
- Consumes existing `tests.test_mnemonic.find_unescaped_ampersand_sinks(root) -> list`; import it directly without editing its module.
- Produces `ai_manager.ui.about_dialog.AboutDialog(QDialog)` with `AboutDialog.__init__(self, parent: Optional[QWidget] = None, version: Optional[str] = None) -> None`, `self.version: str`, and `AboutDialog.sizeHint(self) -> QSize`.
- Constructor ownership is `super().__init__(parent)` and the default expression is evaluated inside the constructor: `self.version = __version__ if version is None else version`; the class accepts no settings/service argument and defines no application-specific signals.
- Produces the three unique text-label object names `aboutNameLabel`, `aboutVersionLabel`, and `aboutDescriptionLabel`; entry points will use inherited `AboutDialog.exec(self) -> int` and discard its return value.

- [ ] **Step 1: Write content, hierarchy, and icon-provenance tests (2–5 minutes)**

Create `tests/test_about_dialog.py` with this first block. The fourth content label is the icon; all four labels belong directly to the dialog. The fixed width is 360 px in Qt logical coordinates, and the size hint must also report 360.

```python
import pytest
from PyQt6.QtCore import QPoint, QSizeF, Qt, QTimer
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ai_manager import __version__
from ai_manager.ui.about_dialog import AboutDialog
from tests.test_mnemonic import find_unescaped_ampersand_sinks


TEXT_LABEL_NAMES = (
    "aboutNameLabel",
    "aboutVersionLabel",
    "aboutDescriptionLabel",
)


def _icon_label(dialog):
    remaining = [
        label for label in dialog.findChildren(QLabel)
        if label.objectName() not in TEXT_LABEL_NAMES
    ]
    assert len(remaining) == 1
    return remaining[0]


@pytest.fixture
def dialog(qtbot):
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    return dlg


def test_about_dialog_content_and_object_names(dialog):
    assert dialog.windowTitle() == "About ai-manager"
    expected = {
        "aboutNameLabel": "ai-manager",
        "aboutVersionLabel": f"Version {__version__}",
        "aboutDescriptionLabel":
            "Desktop administration GUI for local AI backends",
    }
    for name, text in expected.items():
        assert len(dialog.findChildren(QLabel, name)) == 1
        label = dialog.findChild(QLabel, name)
        assert label.text() == text
        assert label.textFormat() == Qt.TextFormat.PlainText
    labels = dialog.findChildren(QLabel)
    assert len(labels) == 4
    assert all(label.buddy() is None for label in labels)
    icon = _icon_label(dialog)
    assert icon.text() == ""
    pixmap = icon.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.deviceIndependentSize() == QSizeF(48, 48)


def test_about_dialog_hierarchy_and_geometry(dialog):
    outer = dialog.layout()
    assert isinstance(outer, QVBoxLayout)
    assert outer.count() == 3
    header = outer.itemAt(0).layout()
    assert isinstance(header, QHBoxLayout)
    assert header.count() == 2
    assert header.itemAt(0).widget() is _icon_label(dialog)
    text_layout = header.itemAt(1).layout()
    assert isinstance(text_layout, QVBoxLayout)
    assert text_layout.count() == 2
    assert text_layout.itemAt(0).widget() is dialog.findChild(
        QLabel, "aboutNameLabel"
    )
    assert text_layout.itemAt(1).widget() is dialog.findChild(
        QLabel, "aboutVersionLabel"
    )
    description = dialog.findChild(QLabel, "aboutDescriptionLabel")
    assert outer.itemAt(1).widget() is description
    boxes = dialog.findChildren(QDialogButtonBox)
    assert len(boxes) == 1
    box = boxes[0]
    assert outer.itemAt(2).widget() is box
    assert all(
        widget.parentWidget() is dialog
        for widget in [*dialog.findChildren(QLabel), box]
    )
    assert dialog.minimumWidth() == dialog.maximumWidth() == dialog.width() == 360
    assert dialog.sizeHint().width() == 360
    assert dialog.minimumHeight() < dialog.maximumHeight()
    assert description.wordWrap() is False
    assert dialog.isModal() is True
    assert dialog.isSizeGripEnabled() is False
    assert box.orientation() == Qt.Orientation.Horizontal
    dialog.show()
    outer.activate()
    box.layout().activate()
    QApplication.processEvents()
    assert box.buttons()
    for button in box.buttons():
        assert button.mapTo(box, QPoint(0, 0)).x() > box.width() / 2


def test_about_dialog_uses_color_icon(qtbot, monkeypatch):
    sentinel = QPixmap(1, 1)
    sentinel.fill(QColor("magenta"))
    calls = []

    def sentinel_icon():
        calls.append(True)
        return QIcon(sentinel)

    monkeypatch.setattr("ai_manager.ui.about_dialog.color_icon", sentinel_icon)
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    assert calls == [True]
    pixmap = _icon_label(dlg).pixmap()
    assert pixmap is not None and not pixmap.isNull()
    image = pixmap.toImage()
    assert image.pixelColor(image.width() // 2, image.height() // 2) == QColor(
        "magenta"
    )
```

- [ ] **Step 2: Write propagation, parent, Close, and mnemonic tests (2–5 minutes)**

Append these functions to `tests/test_about_dialog.py`. The Close test clicks the actual standard button while `exec()` is running; it must never call `accept()` itself.

```python
def test_about_dialog_version_propagates_from_source(qtbot, monkeypatch):
    monkeypatch.setattr("ai_manager.ui.about_dialog.__version__", "9.8.7")
    dlg = AboutDialog()
    qtbot.addWidget(dlg)
    assert dlg.findChild(QLabel, "aboutVersionLabel").text() == "Version 9.8.7"


def test_about_dialog_parent_is_supplied_widget(qtbot):
    sentinel_widget = QWidget()
    qtbot.addWidget(sentinel_widget)
    dlg = AboutDialog(parent=sentinel_widget)
    qtbot.addWidget(dlg)
    assert dlg.parentWidget() is sentinel_widget


@pytest.mark.parametrize("version", ["9.8.7", "0.2.0rc1"])
def test_about_dialog_accepts_injected_version(qtbot, version):
    dlg = AboutDialog(version=version)
    qtbot.addWidget(dlg)
    assert dlg.findChild(QLabel, "aboutVersionLabel").text() == f"Version {version}"


def test_close_button_accepts_dialog(dialog):
    box = dialog.findChild(QDialogButtonBox)
    close_button = box.button(QDialogButtonBox.StandardButton.Close)
    assert close_button is not None
    assert box.standardButtons() == QDialogButtonBox.StandardButton.Close
    assert box.buttons() == [close_button]
    assert close_button.text() == "Close"
    assert box.buttonRole(close_button) == QDialogButtonBox.ButtonRole.RejectRole
    QTimer.singleShot(0, close_button.click)
    assert dialog.exec() == QDialog.DialogCode.Accepted
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_about_dialog_has_no_unescaped_ampersands(dialog):
    box = dialog.findChild(QDialogButtonBox)
    assert box.button(QDialogButtonBox.StandardButton.Close) is not None
    assert find_unescaped_ampersand_sinks(dialog) == []
```

- [ ] **Step 3: Run the new tests and confirm the missing component is red (2–5 minutes)**

Run: `AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src pytest tests/test_about_dialog.py -q`

Expected: collection fails because `ai_manager.ui.about_dialog` does not exist. Fix any unrelated test syntax/import typo before continuing; do not create a stub to hide the missing implementation.

- [ ] **Step 4: Write the complete dialog implementation (2–5 minutes)**

Create `src/ai_manager/ui/about_dialog.py` with exactly this implementation. Use the inherited application stylesheet and Qt placement; add no `move()`, `resize()`, `setFixedHeight()`, settings access, desktop-service operation, version fallback, or custom signal. The `sizeHint()` override makes the specified width independent of the natural text width while keeping the natural content height.

```python
"""Read-only application identity and version dialog."""

from typing import Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ai_manager import __version__
from ai_manager.ui.icons import color_icon


class AboutDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        version: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self.version = __version__ if version is None else version
        self.setWindowTitle("About ai-manager")
        self.setModal(True)
        self.setFixedWidth(360)
        self.setSizeGripEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        header = QHBoxLayout()
        icon_label = QLabel(self)
        icon_label.setPixmap(color_icon().pixmap(48, 48))
        header.addWidget(icon_label)

        text_layout = QVBoxLayout()
        name_label = QLabel("ai-manager", self)
        name_label.setObjectName("aboutNameLabel")
        name_label.setTextFormat(Qt.TextFormat.PlainText)
        version_label = QLabel(f"Version {self.version}", self)
        version_label.setObjectName("aboutVersionLabel")
        version_label.setTextFormat(Qt.TextFormat.PlainText)
        text_layout.addWidget(name_label)
        text_layout.addWidget(version_label)
        header.addLayout(text_layout)
        layout.addLayout(header)

        description = QLabel(
            "Desktop administration GUI for local AI backends", self
        )
        description.setObjectName("aboutDescriptionLabel")
        description.setTextFormat(Qt.TextFormat.PlainText)
        description.setWordWrap(False)
        layout.addWidget(description)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            Qt.Orientation.Horizontal,
            self,
        )
        button_box.setCenterButtons(False)
        button_box.button(QDialogButtonBox.StandardButton.Close).clicked.connect(
            self.accept
        )
        layout.addWidget(button_box)

    def sizeHint(self) -> QSize:
        return QSize(360, super().sizeHint().height())
```

Do not connect `button_box.rejected` to `self.reject`: Close has RejectRole, but this dialog deliberately returns Accepted for its button click. A connection to only `button_box.accepted` would not handle standard Close.

- [ ] **Step 5: Run the complete dialog and unchanged mnemonic tests (2–5 minutes)**

Run: `AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src pytest tests/test_about_dialog.py tests/test_mnemonic.py -q`

Expected: PASS with no failures, including both injected version parameters and the actual Close-button event-loop test. Keep the existing mnemonic module unchanged.

- [ ] **Step 6: Commit (2–5 minutes)**

```bash
git add src/ai_manager/ui/about_dialog.py tests/test_about_dialog.py
git commit -m "feat(ui): add modal About dialog with imported version"
```

## Task 2: Add the versioned title and tray About entry point

**Implementer tier:** Advanced

**Files:**

- Modify: `src/ai_manager/ui/main_window.py:18-39` (imports)
- Modify: `src/ai_manager/ui/main_window.py:103-104` (tray connections)
- Modify: `src/ai_manager/ui/main_window.py:130-132` (title)
- Modify: `src/ai_manager/ui/main_window.py:352-358` (adjacent About method)
- Modify: `src/ai_manager/ui/system_tray.py:32-38` (signal declarations)
- Modify: `src/ai_manager/ui/system_tray.py:73-79` (menu insertion)
- Modify: `tests/test_main_window.py:1-11` (imports)
- Modify: `tests/test_main_window.py:116-116` (append cases)
- Modify: `tests/test_system_tray.py:21-51` (order and action cases)
- Modify: `tests/test_system_tray.py:64-70` (visibility assertions)
- Read only: `tests/test_main_window.py:14-39` (`make_test_window`)
- Read only: `tests/test_system_tray.py:72-77` (availability regression)
- Read only: `tests/test_mnemonic.py:210-244` (main-window sweep)

**Interfaces:**

- Consumes Task 1's `AboutDialog.__init__(self, parent: Optional[QWidget] = None, version: Optional[str] = None) -> None` from `ai_manager.ui.about_dialog`; its default version is resolved inside the real constructor, and inherited `exec(self) -> int` is called once per instance.
- Consumes existing `ai_manager.__version__: str` with `from ai_manager import __version__`; this is a consumer-module binding, so propagation tests patch `ai_manager.ui.main_window.__version__`.
- Consumes existing `make_test_window(qtbot, tmp_path)` from this same test module, returning a registered `MainWindow` with copied backend fixtures and mocked status sinks; do not replace it or weaken its assertions.
- Preserves `SystemTrayManager.is_available(self) -> bool` and `SystemTrayManager.update_visibility_action_text(self, is_window_visible: bool) -> None`.
- Produces `SystemTrayManager.about_requested = pyqtSignal()`, a no-argument signal, and `SystemTrayManager._about_action: QAction` at menu index 6; each action trigger emits exactly one empty argument tuple.
- Produces `MainWindow.open_about_dialog(self) -> None`, which constructs `AboutDialog(self)` positionally, invokes `exec()` once, and discards its result; connects `self.tray_manager.about_requested.connect(self.open_about_dialog)`.

- [ ] **Step 1: Pin exact tray structure and single emissions (2–5 minutes)**

Replace only the two identified test functions and the action parameter list in `tests/test_system_tray.py` with the following. Keep all other tray tests and their assertions, including the availability test, unchanged.

```python
def test_context_menu_order_and_structure(manager):
    actions = manager._context_menu.actions()
    assert [a.text() for a in actions] == [
        "Show ai-manager",
        "",
        "Start All Supervised Services",
        "Stop All Supervised Services",
        "",
        "⚙ Settings...",
        "About ai-manager",
        "",
        "Quit ai-manager",
    ]
    assert [index for index, action in enumerate(actions)
            if action.isSeparator()] == [1, 4, 7]
    assert actions[6] is manager._about_action


@pytest.mark.parametrize(
    "attr, signal_name",
    [
        ("_toggle_action", "toggle_window_requested"),
        ("_start_all_action", "start_all_services_requested"),
        ("_stop_all_action", "stop_all_services_requested"),
        ("_settings_action", "open_settings_requested"),
        ("_about_action", "about_requested"),
        ("_quit_action", "quit_requested"),
    ],
)
def test_menu_action_emits_expected_signal(qtbot, manager, attr, signal_name):
    action = getattr(manager, attr)
    signal = getattr(manager, signal_name)
    emissions = []
    signal.connect(lambda *args: emissions.append(args))
    with qtbot.waitSignal(signal, timeout=1000):
        action.trigger()
    assert emissions == [()]
```

- [ ] **Step 2: Extend the visibility regression without weakening availability (2–5 minutes)**

Replace `test_update_visibility_action_text` with this code:

```python
def test_update_visibility_action_text(manager):
    actions = manager._context_menu.actions()
    snapshot = [action.text() for action in actions]

    manager.update_visibility_action_text(True)
    assert manager._toggle_action.text() == "Hide ai-manager"
    current = manager._context_menu.actions()
    assert current == actions
    assert [action.text() for action in current] == [
        "Hide ai-manager", *snapshot[1:]
    ]

    manager.update_visibility_action_text(False)
    assert manager._toggle_action.text() == "Show ai-manager"
    current = manager._context_menu.actions()
    assert current == actions
    assert [action.text() for action in current] == [
        "Show ai-manager", *snapshot[1:]
    ]
```

Retain `test_is_available_is_not_cached` verbatim, including both probes on the same manager:

```python
def test_is_available_is_not_cached(mock_tray_available, manager):
    mock_tray_available(False)
    assert manager.is_available() is False

    mock_tray_available(True)
    assert manager.is_available() is True
```

- [ ] **Step 3: Write title-propagation and entry-point tests (2–5 minutes)**

In `tests/test_main_window.py`, extend the existing mock import to `from unittest.mock import MagicMock, call`, add `from ai_manager import __version__` and `from ai_manager.ui import main_window as main_window_module`, and append these functions. Every new window uses the existing fixture-copying helper.

```python
def test_main_window_title_includes_version(qtbot, tmp_path):
    window = make_test_window(qtbot, tmp_path)
    assert window.windowTitle() == (
        f"ai-manager v{__version__} — AI Provider Configuration & Service Controller"
    )
    assert f"v{__version__}" in window.windowTitle()
    assert "&" in window.windowTitle()


def test_title_propagates_patched_source_version(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(main_window_module, "__version__", "9.8.7")
    window = make_test_window(qtbot, tmp_path)
    assert window.windowTitle() == (
        "ai-manager v9.8.7 — AI Provider Configuration & Service Controller"
    )


def test_open_about_dialog_constructs_fresh_modal(qtbot, tmp_path, monkeypatch):
    window = make_test_window(qtbot, tmp_path)
    first, second = MagicMock(), MagicMock()
    factory = MagicMock(side_effect=[first, second])
    monkeypatch.setattr(main_window_module, "AboutDialog", factory)

    window.open_about_dialog()
    window.open_about_dialog()

    assert factory.call_args_list == [call(window), call(window)]
    first.exec.assert_called_once_with()
    second.exec.assert_called_once_with()


def test_tray_about_request_opens_about_dialog(qtbot, tmp_path, monkeypatch):
    window = make_test_window(qtbot, tmp_path)
    instance = MagicMock()
    factory = MagicMock(return_value=instance)
    monkeypatch.setattr(main_window_module, "AboutDialog", factory)

    window.tray_manager._about_action.trigger()

    factory.assert_called_once_with(window)
    instance.exec.assert_called_once_with()
```

- [ ] **Step 4: Confirm the new title/action/entry-point cases are red (2–5 minutes)**

Run: `AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src pytest tests/test_main_window.py tests/test_system_tray.py -q`

Expected: the new cases fail for the old title, missing consumer version import, eight-entry menu, and absent About signal/action/method. Existing availability and unrelated cases remain passing.

- [ ] **Step 5: Add the tray signal and action (2–5 minutes)**

In `SystemTrayManager`, place this declaration beside `open_settings_requested`:

```python
    about_requested = pyqtSignal()
```

Immediately after the Settings action's connection and before the existing final separator, insert:

```python
        self._about_action = self._context_menu.addAction("About ai-manager")
        self._about_action.triggered.connect(self.about_requested.emit)
```

Keep the separator calls, Quit action, tooltip behavior, availability probe, visibility implementation, and all other tray behavior unchanged. The resulting menu has the nine entries specified in Step 1, separators `[1, 4, 7]`, and About at `6`.

- [ ] **Step 6: Wire MainWindow and interpolate the exact title (2–5 minutes)**

Add these module-scope imports in `src/ai_manager/ui/main_window.py`:

```python
from ai_manager import __version__
from ai_manager.ui.about_dialog import AboutDialog
```

Place this connection beside the existing Settings tray connection in `MainWindow.__init__`:

```python
        self.tray_manager.about_requested.connect(self.open_about_dialog)
```

Replace the `_init_ui()` title statement with:

```python
        self.setWindowTitle(
            f"ai-manager v{__version__} — AI Provider Configuration & Service Controller"
        )
```

Add this method beside `open_settings_dialog`:

```python
    def open_about_dialog(self) -> None:
        """Open a fresh modal About dialog owned by this window."""
        dialog = AboutDialog(self)
        dialog.exec()
```

The title contains U+2014 with surrounding spaces and the literal single `&`; do not pass it through `escape_mnemonic`. There is no cached dialog or version default in MainWindow.

- [ ] **Step 7: Run entry-point, tray, About, and unchanged mnemonic coverage (2–5 minutes)**

Run: `AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src pytest tests/test_main_window.py tests/test_system_tray.py tests/test_about_dialog.py tests/test_mnemonic.py -q`

Expected: PASS with no failures. This includes `test_is_available_is_not_cached`, all six action-signal parameters, and the unchanged `test_main_window_has_no_unescaped_ampersands`, whose required assertions remain:

```python
assert find_unescaped_ampersand_sinks(window) == []
assert window.findChildren(QAbstractButton)
assert window.findChildren(QMenu), "system-tray context menu should be found"
assert "&" in window.windowTitle()
```

- [ ] **Step 8: Commit (2–5 minutes)**

```bash
git add src/ai_manager/ui/main_window.py src/ai_manager/ui/system_tray.py tests/test_main_window.py tests/test_system_tray.py
git commit -m "feat(ui): show version in title and expose About from tray"
```

## Task 3: Add the Settings footer and verify modal ownership without saving

**Implementer tier:** Advanced

**Files:**

- Modify: `src/ai_manager/ui/settings_dialog.py:30-31` (About import)
- Modify: `src/ai_manager/ui/settings_dialog.py:60-69` (footer insertion)
- Modify: `src/ai_manager/ui/settings_dialog.py:151-173` (insert footer builder and About handler adjacent to unchanged button-box builder)
- Modify: `tests/test_settings_dialog.py:8-11` (imports)
- Modify: `tests/test_settings_dialog.py:202-202` (append helper and new cases)
- Read only: `tests/test_settings_dialog.py:14-63` (fake service and fixtures)
- Read only: `tests/test_settings_dialog.py:112-128` (Save regression)
- Read only: `tests/test_settings_dialog.py:194-202` (Cancel regression)
- Read only: `tests/test_mnemonic.py:182-207` (Settings sweep)

**Interfaces:**

- Consumes Task 1's `AboutDialog.__init__(self, parent: Optional[QWidget] = None, version: Optional[str] = None) -> None` and inherited `AboutDialog.exec(self) -> int` from `ai_manager.ui.about_dialog`; use `AboutDialog(parent=self)` with a keyword parent and no version override.
- Consumes existing `SettingsDialog.__init__(self, settings: UserSettings, desktop_service: DesktopIntegrationService, parent: Optional[QWidget] = None)` and `settings_saved = pyqtSignal(UserSettings)` without changing either signature.
- Preserves existing `_build_button_box(self) -> QDialogButtonBox`, `_on_save(self) -> None`, `btn_save: QPushButton`, and `btn_cancel: QPushButton`, including Save/Cancel standard-button membership, texts, ordering, aliases, and accepted/rejected wiring.
- Consumes existing `dialog(qtbot, settings, service)`, `settings()`, and `service()` pytest fixtures and the existing `mock_tray_available(monkeypatch)` fixture, whose returned setter accepts an availability boolean before Settings construction.
- Consumes `FakeDesktopService.autostart_calls: list`, `install_calls: int`, and `remove_calls: int` as side-effect counters; opening About must not call any desktop operation or `_on_save`.
- Produces `SettingsDialog._build_footer(self) -> QHBoxLayout`, `SettingsDialog._open_about_dialog(self) -> None`, and `btn_about: QPushButton`; the footer order is exactly About/stretch/button box.

- [ ] **Step 1: Add the complete snapshot helper and footer-geometry test (2–5 minutes)**

Add these imports to `tests/test_settings_dialog.py`, retaining its current imports:

```python
from unittest.mock import MagicMock, call

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QPushButton,
)

from ai_manager.ui import settings_dialog as settings_dialog_module
from ai_manager.ui.about_dialog import AboutDialog
```

Append the helper and test below. Snapshots copy both models, every editable control value (three checkboxes, theme, poll interval), and all three recorded service counters.

```python
def _about_snapshot(settings, dlg, service):
    return (
        settings.model_dump(),
        dlg.settings.model_dump(),
        (
            dlg.chk_close_to_tray.isChecked(),
            dlg.chk_start_minimized.isChecked(),
            dlg.chk_autostart.isChecked(),
            dlg.cmb_theme.currentData(),
            dlg.cmb_poll_interval.currentData(),
        ),
        list(service.autostart_calls),
        service.install_calls,
        service.remove_calls,
    )


def test_about_button_sits_left_of_action_buttons(dialog):
    assert isinstance(dialog.btn_about, QPushButton)
    assert dialog.btn_about.text() == "About ai-manager"
    assert dialog.btn_about.parentWidget() is dialog
    boxes = dialog.findChildren(QDialogButtonBox)
    assert len(boxes) == 1
    box = boxes[0]
    assert dialog.btn_about not in box.buttons()
    assert box.orientation() == Qt.Orientation.Horizontal
    assert box.standardButtons() == (
        QDialogButtonBox.StandardButton.Save
        | QDialogButtonBox.StandardButton.Cancel
    )
    assert box.button(QDialogButtonBox.StandardButton.Save) is dialog.btn_save
    assert box.button(QDialogButtonBox.StandardButton.Cancel) is dialog.btn_cancel
    assert dialog.btn_save.text() == "Save && Apply"
    assert dialog.btn_cancel.text() == "Cancel"
    assert set(box.buttons()) == {dialog.btn_save, dialog.btn_cancel}
    outer = dialog.layout()
    footer = outer.itemAt(outer.count() - 1).layout()
    assert isinstance(footer, QHBoxLayout)
    assert footer.count() == 3
    assert footer.itemAt(0).widget() is dialog.btn_about
    spacer = footer.itemAt(1).spacerItem()
    assert spacer is not None
    assert spacer.expandingDirections() & Qt.Orientation.Horizontal
    assert footer.stretch(1) == 1
    assert footer.itemAt(2).widget() is box
    dialog.show()
    outer.activate()
    footer.activate()
    box.layout().activate()
    QApplication.processEvents()
    about_right = (
        dialog.btn_about.mapTo(dialog, QPoint(0, 0)).x()
        + dialog.btn_about.width()
    )
    for btn_x in (dialog.btn_save, dialog.btn_cancel):
        assert about_right <= btn_x.mapTo(dialog, QPoint(0, 0)).x()
```

- [ ] **Step 2: Write factory-seam no-save and freshness tests (2–5 minutes)**

Append these tests. The tray availability setter runs before constructing the dialog. The factory seam deliberately uses two distinct instances for two invocations and proves only call behavior; the next step covers the real constructor separately.

```python
@pytest.mark.parametrize("tray_available", [True, False])
def test_about_button_opens_about_without_saving(
    qtbot, settings, service, monkeypatch, mock_tray_available, tray_available
):
    mock_tray_available(tray_available)
    dlg = SettingsDialog(settings, service)
    qtbot.addWidget(dlg)
    dlg.chk_autostart.setChecked(True)
    before = _about_snapshot(settings, dlg, service)
    saved, accepted, rejected = [], [], []
    dlg.settings_saved.connect(saved.append)
    dlg.accepted.connect(lambda: accepted.append(True))
    dlg.rejected.connect(lambda: rejected.append(True))
    instance = MagicMock()
    factory = MagicMock(return_value=instance)
    monkeypatch.setattr(settings_dialog_module, "AboutDialog", factory)

    dlg.btn_about.click()

    factory.assert_called_once_with(parent=dlg)
    instance.exec.assert_called_once_with()
    assert saved == []
    assert accepted == []
    assert rejected == []
    assert _about_snapshot(settings, dlg, service) == before
    assert dlg.chk_autostart.isChecked() is True


def test_about_button_constructs_fresh_dialog_each_time(dialog, monkeypatch):
    saved = []
    dialog.settings_saved.connect(saved.append)
    first, second = MagicMock(), MagicMock()
    factory = MagicMock(side_effect=[first, second])
    monkeypatch.setattr(settings_dialog_module, "AboutDialog", factory)

    dialog.btn_about.click()
    dialog.btn_about.click()

    assert factory.call_args_list == [call(parent=dialog), call(parent=dialog)]
    first.exec.assert_called_once_with()
    second.exec.assert_called_once_with()
    assert saved == []
```

- [ ] **Step 3: Write the real-constructor seam while Settings executes modally (2–5 minutes)**

Append this test. Patch only the real class's `exec`, leaving the module factory and `__init__` intact. Record the post-click state before explicitly rejecting Settings for test cleanup; the cleanup signal must not be confused with an About side effect. Running the click from a timer inside Settings' actual `exec()` also covers nested modal ownership.

```python
def test_about_click_uses_real_dialog_parented_to_settings(
    qtbot, settings, service, dialog, monkeypatch
):
    dlg = dialog
    dlg.chk_autostart.setChecked(True)
    before = _about_snapshot(settings, dlg, service)
    saved, accepted, rejected = [], [], []
    dlg.settings_saved.connect(saved.append)
    dlg.accepted.connect(lambda: accepted.append(True))
    dlg.rejected.connect(lambda: rejected.append(True))
    instances = []

    def recorder(self):
        qtbot.addWidget(self)
        instances.append((self, self.parentWidget()))
        return 1

    monkeypatch.setattr(AboutDialog, "exec", recorder)
    observed = []

    def click_and_capture():
        try:
            dlg.btn_about.click()
            observed.append((
                dlg.isVisible(),
                dlg.isModal(),
                dlg.result(),
                _about_snapshot(settings, dlg, service),
                list(saved),
                list(accepted),
                list(rejected),
                dlg.chk_autostart.isChecked(),
            ))
        finally:
            dlg.reject()

    dlg.show()
    QTimer.singleShot(0, click_and_capture)
    assert dlg.exec() == QDialog.DialogCode.Rejected

    assert len(instances) == 1
    about, supplied_parent = instances[0]
    assert isinstance(about, AboutDialog)
    assert supplied_parent is dlg
    assert about.parentWidget() is dlg
    assert about.isModal() is True
    assert observed == [(
        True, True, QDialog.DialogCode.Rejected, before, [], [], [], True
    )]
    assert saved == []
    assert accepted == []
```

- [ ] **Step 4: Confirm the missing footer is red (2–5 minutes)**

Run: `AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src pytest tests/test_settings_dialog.py -q`

Expected: the new cases fail because `btn_about` and the footer are absent; the existing Save and Cancel cases remain passing. The real-constructor test's `finally` must leave its modal loop even on a failure.

- [ ] **Step 5: Build the footer and direct Settings-owned About handler (2–5 minutes)**

Add this module-scope import to `src/ai_manager/ui/settings_dialog.py`:

```python
from ai_manager.ui.about_dialog import AboutDialog
```

Replace only the final `layout.addWidget(self._build_button_box())` in `_init_ui()` with:

```python
        layout.addLayout(self._build_footer())
```

Insert these methods adjacent to `_build_button_box()`, leaving the entire existing button-box method unchanged:

```python
    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        self.btn_about = QPushButton("About ai-manager", self)
        self.btn_about.clicked.connect(self._open_about_dialog)
        footer.addWidget(self.btn_about)
        footer.addStretch(1)
        footer.addWidget(self._build_button_box())
        return footer

    def _open_about_dialog(self) -> None:
        dialog = AboutDialog(parent=self)
        dialog.exec()
```

The button is a sibling of the button box, never an ActionRole member. This construction resolves Q1 by keeping About left of both commit buttons under the project's Qt style. Do not route the click through MainWindow or modify `_on_save`, settings, service calls, standard-button roles, or button-box signal wiring.

- [ ] **Step 6: Run all Settings, About, and unchanged mnemonic tests (2–5 minutes)**

Run: `AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src pytest tests/test_settings_dialog.py tests/test_about_dialog.py tests/test_mnemonic.py -q`

Expected: PASS with no failures, including both tray-availability parameters and the real modal Settings case. Retain `test_save_emits_settings_and_syncs_autostart` unchanged, including:

```python
assert isinstance(emitted, UserSettings)
assert emitted.autostart is True
assert emitted.start_minimized is True
assert service.autostart_calls == [(True, True)]
assert dlg.result() == 1
```

Retain `test_cancel_rejects_without_saving` unchanged, including:

```python
assert dlg.result() == 0
assert service.autostart_calls == []
```

Retain `test_settings_dialog_has_no_unescaped_ampersands` unchanged, including its non-vacuity checks; the new About button is traversed automatically:

```python
assert find_unescaped_ampersand_sinks(dlg) == []
assert dlg.btn_save.text() == "Save && Apply"
assert "Desktop && Application Menu" in [
    group.title() for group in dlg.findChildren(QGroupBox)
]
```

- [ ] **Step 7: Commit (2–5 minutes)**

```bash
git add src/ai_manager/ui/settings_dialog.py tests/test_settings_dialog.py
git commit -m "feat(settings): open About from a separate footer button"
```

## Task 4: Derive packaging version and validate release documentation

**Implementer tier:** Standard

**Files:**

- Modify: `pyproject.toml:5-15` (dynamic project version and author)
- Modify: `pyproject.toml:27-29` (append setuptools dynamic table)
- Create: `tests/test_version.py`
- Modify: `README.md:7-13` (feature bullet)
- Modify: `README.md:31-38` (release note after editable-install instructions)
- Create: `tests/test_readme_documents_version.py`
- Read only: `src/ai_manager/__init__.py:1-3`
- Read only: `src/ai_manager/ui/about_dialog.py` (Task 1 output)
- Read only: `src/ai_manager/ui/main_window.py` (Task 2 output)

**Interfaces:**

- Consumes existing `ai_manager.__version__: str`, the unchanged literal `__version__ = "0.1.3"`; setuptools statically reads the same symbol through `version = {attr = "ai_manager.__version__"}`.
- Consumes Task 1's `AboutDialog.__init__(self, parent: Optional[QWidget] = None, version: Optional[str] = None) -> None`, whose module imports `__version__`, and Task 2's `MainWindow.open_about_dialog(self) -> None`, whose module imports the same symbol for the title; both consumer modules must lack version literals and forbidden runtime imports.
- Consumes Task 2's `SystemTrayManager.about_requested = pyqtSignal()` with no arguments and Task 3's `SettingsDialog._build_footer(self) -> QHBoxLayout` and `_open_about_dialog(self) -> None` only through the final full-suite regression gate; no UI files are modified in this task.
- Produces PEP 621 `project.dynamic == ["version"]` with no `project.version`, `tool.setuptools.dynamic.version == {"attr": "ai_manager.__version__"}`, and `project.authors == [{"name": "Henry", "email": "wenhepku@gmail.com"}]`.
- Produces README text verified through `test_readme_documents_version_display` and a wheel whose sole `.dist-info/METADATA` has `Name: ai-manager` and exactly one `Version` equal to the imported source version.

- [ ] **Step 1: Write format, packaging, literal, and import-purity tests (2–5 minutes)**

Create `tests/test_version.py` with this block. The AST store-name check rejects any other assignment anywhere in the module, including annotated, augmented, nested, or destructured bindings, while requiring the actual version source to be the single top-level string assignment.

```python
import ast
from pathlib import Path
import re
import tomllib

from ai_manager import __version__


ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "ai_manager" / "__init__.py"


def test_version_is_release_triplet():
    assert re.fullmatch(r"^\d+\.\d+\.\d+$", __version__) is not None


def test_pyproject_derives_version():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert project["name"] == "ai-manager"
    assert "version" not in project
    assert project["dynamic"] == ["version"]
    assert data["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "ai_manager.__version__"
    }
    assert project["authors"] == [
        {"name": "Henry", "email": "wenhepku@gmail.com"}
    ]
    assert project["description"] == (
        "Desktop administration GUI for local AI backends"
    )
    assert project["dependencies"] == [
        "PyQt6>=6.5.0",
        "pydantic>=2.0.0",
        "ruamel.yaml>=0.18.0",
        "httpx>=0.25.0",
    ]
    assert project["optional-dependencies"]["dev"] == [
        "pytest>=7.0.0",
        "pytest-qt>=4.2.0",
        "respx>=0.20.0",
    ]
    assert project["scripts"] == {"ai-manager": "ai_manager.main:main"}
    assert data["build-system"] == {
        "requires": ["setuptools>=61.0"],
        "build-backend": "setuptools.build_meta",
    }
    assert data["tool"]["setuptools"]["package-data"]["ai_manager"] == [
        "resources/icons/*.svg"
    ]


def test_version_literal_is_static_string():
    tree = ast.parse(VERSION_FILE.read_text(encoding="utf-8"))
    assignments = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    assignment = assignments[0]
    assert isinstance(assignment.value, ast.Constant)
    assert isinstance(assignment.value.value, str)
    version_stores = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "__version__"
        and isinstance(node.ctx, ast.Store)
    ]
    assert len(version_stores) == 1
    assert version_stores[0] in assignment.targets


def test_version_init_has_no_imports():
    tree = ast.parse(VERSION_FILE.read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body
    )
```

- [ ] **Step 2: Write consumer-source and exact README tests (2–5 minutes)**

Append this function to `tests/test_version.py`:

```python
def test_version_consumers_import_the_symbol():
    forbidden = (
        "importlib", "importlib.metadata", "subprocess", "platform", "tomllib"
    )
    for relative in (
        "src/ai_manager/ui/main_window.py",
        "src/ai_manager/ui/about_dialog.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert any(
            isinstance(node, ast.ImportFrom)
            and node.module == "ai_manager"
            and any(alias.name == "__version__" for alias in node.names)
            for node in ast.walk(tree)
        ), relative
        assert re.search(r"\d+\.\d+\.\d+", source) is None, relative
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ), (relative, name)
```

Create `tests/test_readme_documents_version.py` with the full test below. Concatenated Python strings preserve the two exact required README sentences.

```python
from pathlib import Path


def test_readme_documents_version_display():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(
        encoding="utf-8"
    )
    assert (
        "- **Version Display**: The version appears in the window title and in "
        "the About dialog (tray menu or Settings)."
    ) in readme
    assert (
        "Bump the version only in `src/ai_manager/__init__.py`; packaging "
        "metadata derives from it. Re-run the editable install after a bump."
    ) in readme
```

- [ ] **Step 3: Confirm packaging and documentation are red (2–5 minutes)**

Run: `AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src pytest tests/test_version.py tests/test_readme_documents_version.py -q`

Expected: the packaging test fails because the static project version is still present, and the README test fails because the sentences are absent. The release-triplet, literal, purity, and consumer-import tests pass against the unchanged literal and already integrated Tasks 1–2.

- [ ] **Step 4: Change only the approved packaging declarations (2–5 minutes)**

Replace the `[project]` table in `pyproject.toml` with exactly:

```toml
[project]
name = "ai-manager"
dynamic = ["version"]
description = "Desktop administration GUI for local AI backends"
authors = [{ name = "Henry", email = "wenhepku@gmail.com" }]
dependencies = [
    "PyQt6>=6.5.0",
    "pydantic>=2.0.0",
    "ruamel.yaml>=0.18.0",
    "httpx>=0.25.0",
]
```

Immediately after the unchanged existing package-data table, append:

```toml
[tool.setuptools.dynamic]
version = {attr = "ai_manager.__version__"}
```

Keep `[build-system]`, `[project.optional-dependencies]`, `[project.scripts]`, and `[tool.setuptools.package-data]` exactly as before. Leave `src/ai_manager/__init__.py` unchanged; do not add a second literal or a build/runtime version helper.

- [ ] **Step 5: Add the tested feature bullet and release note verbatim (2–5 minutes)**

Append this exact line to README's existing Features list:

```markdown
- **Version Display**: The version appears in the window title and in the About dialog (tray menu or Settings).
```

After the editable-install command block and before the existing Running Tests section, add this exact release-note paragraph, on one physical line:

```markdown
Bump the version only in `src/ai_manager/__init__.py`; packaging metadata derives from it. Re-run the editable install after a bump.
```

Keep all existing README content. The second sentence records why an editable install must be refreshed before installed distribution metadata such as `pip show ai-manager` reflects a future one-file bump.

- [ ] **Step 6: Run focused source, configuration, and README tests (2–5 minutes)**

Run: `AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src pytest tests/test_version.py tests/test_readme_documents_version.py -q`

Expected: PASS with no failures. This task owns all changes to `pyproject.toml` and `tests/test_version.py`; no earlier task needs to alter either file.

- [ ] **Step 7: Run the exact full-suite acceptance gate (2–5 minutes)**

Run from the implementation worktree root:

```bash
AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src pytest tests/
```

Expected: exit status 0 with no failing tests, including every new/updated case and all unchanged tests. The recorded 216-test baseline is historical, not an expected final count. Do not proceed to wheel verification on a failing suite.

- [ ] **Step 8: Perform the sole non-pytest verification, build and inspect the exact wheel (2–5 minutes)**

Run the approved build command:

```bash
python -m pip wheel --no-deps --no-build-isolation -w dist .
```

Require exit status 0. Then run the exact-wheel inspection below, requiring exit status 0; do not select an arbitrary old file from `dist` and do not add a runtime metadata read.

```bash
PYTHONPATH=src python - <<'PY'
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile
from ai_manager import __version__

wheel = Path("dist") / f"ai_manager-{__version__}-py3-none-any.whl"
assert wheel.is_file(), wheel
with ZipFile(wheel) as archive:
    paths = [name for name in archive.namelist()
             if name.endswith(".dist-info/METADATA")]
    assert len(paths) == 1, paths
    metadata = BytesParser().parsebytes(archive.read(paths[0]))
assert metadata["Name"] == "ai-manager"
assert metadata.get_all("Version") == [__version__]
print(f"Verified {wheel.name}: Version: {__version__}")
PY
```

For the unchanged release the exact produced wheel is `dist/ai_manager-0.1.3-py3-none-any.whl`. Both commands together are the single wheel verification required by specification §10.3.

- [ ] **Step 9: Commit (2–5 minutes)**

```bash
git add pyproject.toml tests/test_version.py README.md tests/test_readme_documents_version.py
git commit -m "build: derive release metadata from the single version literal"
```
