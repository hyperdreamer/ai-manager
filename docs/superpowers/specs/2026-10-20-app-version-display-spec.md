# Technical Specification: App Version Display

Status: derived from the approved
[App Version Display design](2026-10-20-app-version-display-design.md) at HEAD
`45bed61`. The selected visual reference is option **B** in the
[recorded mockup](assets/2026-10-20-app-version-display-options.png).

## 1. Purpose and Scope

Expose the application version in the main window title and an About dialog,
with exactly one authored version value. Packaging derives its version from that
value; UI consumers obtain it through a Python import.

### 1.1 In scope

| Approved requirement | Deliverable |
| --- | --- |
| Display the version | A compact `v<version>` token in the existing main window title and a `Version <version>` line in About. |
| Single source | Retain `src/ai_manager/__init__.py::__version__`; derive setuptools metadata from it so a release bump edits one file. |
| About entry points | One system-tray menu action and one Settings footer button beside the existing Save/Cancel button box. |
| Pure runtime version read | Import the literal; no metadata lookup, file read, subprocess, or fallback in the version-read path. |
| Regression coverage | Version/configuration tests, About tests, entry-point tests, tray menu tests, and the existing mnemonic sweeps. |
| Adjacent packaging correction | Change the author email from `henry@local` to `wenhepku@gmail.com` in the same `[project]` table. |
| Documentation | Add a README feature bullet describing title/About version display and a release note directing version bumps only to `src/ai_manager/__init__.py`. |

### 1.2 Out of scope

- A `--version` command-line flag.
- Git build provenance, commit suffixes, date stamps, and dirty-tree detection.
- License, credits, and third-party-version panes in About.
- Update checking, telemetry, and a new-version banner.
- A version in the tray tooltip.
- Changing the current version value, `0.1.4`.

### 1.3 File responsibilities

| File | Required treatment |
| --- | --- |
| `pyproject.toml` | Replace the static version with dynamic version configuration; correct the author email. |
| `src/ai_manager/__init__.py` | Retain the existing module-level literal unchanged. |
| `src/ai_manager/ui/about_dialog.py` | Add the leaf `AboutDialog` component specified in §4. |
| `src/ai_manager/ui/main_window.py` | Import the version and About dialog; change the title; add the tray connection and About entry point. |
| `src/ai_manager/ui/system_tray.py` | Add the About signal and action in the position specified in §6. |
| `src/ai_manager/ui/settings_dialog.py` | Add a left-aligned About push button in a footer row beside the existing Save/Cancel button box, and open About with Settings as parent. |
| `src/ai_manager/ui/icons.py`, `src/ai_manager/ui/mnemonic.py` | Reuse their existing APIs without edits. |
| `tests/test_version.py`, `tests/test_about_dialog.py` | Add the tests in §9. |
| `tests/test_main_window.py`, `tests/test_system_tray.py`, `tests/test_settings_dialog.py` | Add/update only the cases identified in §9. |
| `tests/test_mnemonic.py` | Retain its helper and existing assertions; reuse the helper for the new About sweep. |
| `README.md` | Add the two documentation items in §1.1. |

There is no new service, persisted state, settings key, or dependency.

## 2. Packaging Configuration

### 2.1 Current `[project]` table

The complete current table in `pyproject.toml` is:

```toml
[project]
name = "ai-manager"
version = "0.1.4"
description = "Desktop administration GUI for local AI backends"
authors = [{ name = "Henry", email = "henry@local" }]
dependencies = [
    "PyQt6>=6.5.0",
    "pydantic>=2.0.0",
    "ruamel.yaml>=0.18.0",
    "httpx>=0.25.0",
]
```

### 2.2 Final `[project]` table

Replace that table with exactly:

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

`[project].version` must be absent, including when `dynamic` is present. The
corrected email is part of the approved change because the design's wheel-build
verification requires valid author metadata.

### 2.3 Final setuptools fragment

There is currently no `[tool.setuptools.dynamic]` table. Append the following
immediately after the existing `[tool.setuptools.package-data]` table:

```toml
[tool.setuptools.dynamic]
version = {attr = "ai_manager.__version__"}
```

Keep the current build backend, `setuptools>=61.0` requirement, dependencies,
optional dependencies, console script, and package-data declarations. Setuptools
resolves the module-level string assignment through its static attribute reader.
A computed version expression would permit an import fallback at build time and
violates the literal contract in §3.

## 3. Version Source Contract

The source of truth remains the existing assignment in
`src/ai_manager/__init__.py`:

```python
__version__ = "0.1.4"
```

Consumers in `main_window.py` and `about_dialog.py` use this import path:

```python
from ai_manager import __version__
```

| Contract | Required behaviour |
| --- | --- |
| Authored value | Exactly one authored application-version **source** exists anywhere in the repository: the module-level string assigned to `ai_manager.__version__`. The version string may legitimately appear in documentation prose, injected test data, and derived packaging metadata; those occurrences are not sources and must not be edited independently. |
| Literal form | The assignment is a single module-level `ast.Assign` to `__version__` whose value is an `ast.Constant` of type `str`. Concatenation, `join`, f-strings, ternaries, `importlib` lookups, and environment reads are forbidden: a computed value would silently break both the setuptools static reader and the single-source guarantee. |
| Import purity | `src/ai_manager/__init__.py` contains no `Import` or `ImportFrom` node in its module body. Importing `ai_manager` therefore performs no IO, no distribution-metadata lookup, no subprocess call, and defines no side effects. |
| Consumer imports | `main_window.py` and `about_dialog.py` each contain an `ImportFrom` with `module == "ai_manager"` and alias `name == "__version__"`. Neither module contains a version literal, and neither imports `importlib`, `importlib.metadata`, `subprocess`, `platform`, or `tomllib`. |
| Other occurrences | UI text and packaging configuration derive from that symbol. Documentation examples and injected test data do not establish another application-version source; tests asserting the current version import the symbol. |
| Import behaviour | The version read performs no IO, distribution-metadata lookup, subprocess call, exception handling, or fallback. A source checkout does not need an installed distribution to render its version. |
| Propagation | Assigning a different value to the consumer module's imported `__version__` changes the rendered surface: the window title and the About version label both follow it. `AboutDialog` therefore resolves its default inside `__init__` (§4.1), never in a frozen default-argument binding. |
| Current release scheme | The version matches `^\d+\.\d+\.\d+$` exactly. This change retains the current value, `0.1.4`. |
| Rendering | Title and About interpolate the supplied version unchanged. UI code does not validate, normalize, prefix with a git identifier, or truncate that value. |
| Future release bump | Edit only the literal in `src/ai_manager/__init__.py`; packaging and default UI text derive from it. |
| Editable installation | After a version bump, rerun the editable installation before expecting `pip show ai-manager` to reflect the new value. Record this consequence in the release note. |

## 4. Module `ai_manager.ui.about_dialog`

### 4.1 Public API and ownership

Create `src/ai_manager/ui/about_dialog.py` with this constructor contract:

```python
from typing import Optional
from PyQt6.QtWidgets import QDialog, QWidget
from ai_manager import __version__

class AboutDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        version: Optional[str] = None,
    ) -> None:
        self.version = __version__ if version is None else version
```

The default is resolved **inside** `__init__` from the module-level imported
symbol, not captured in a default-argument expression. A default of
`version: str = __version__` would freeze the value at import time and silently
defeat the propagation contract in §3; it is forbidden.

`parent` is passed to `QDialog`; `dialog.parentWidget()` is that same widget.
Passing `version=` overrides only the displayed version for that instance. The
dialog accepts no settings object or desktop service, defines no
application-specific signals, and performs no settings, configuration, or
desktop-integration operations. Standard QDialog lifecycle signals still occur
when the dialog finishes.

### 4.2 Text, icon, and test lookup contracts

| Element | Qt type / lookup | Exact content or behaviour |
| --- | --- | --- |
| Window title | `AboutDialog.windowTitle()` | `About ai-manager` |
| Application icon | The content `QLabel` with a pixmap, distinct from the three named text labels | Empty text; a 48 × 48 logical-pixel pixmap produced by calling `color_icon()` through the `about_dialog` module name. `about_dialog.py` must import it at module scope (`from ai_manager.ui.icons import color_icon`) so tests can patch that attribute with a sentinel icon and prove the call. |
| Name | `QLabel`, object name `aboutNameLabel` | `ai-manager` |
| Version | `QLabel`, object name `aboutVersionLabel` | `f"Version {version}"`, with exactly one space after `Version`. |
| Description | `QLabel`, object name `aboutDescriptionLabel` | `Desktop administration GUI for local AI backends` on one line. |
| Button box | The single child `QDialogButtonBox` | Horizontal; only `QDialogButtonBox.StandardButton.Close`; buttons aligned to the right. |
| Close button | `button_box.button(QDialogButtonBox.StandardButton.Close)` | Label `Close`; role `QDialogButtonBox.ButtonRole.RejectRole`. |

Each named label exists exactly once. None of the content labels has a buddy.
The three text labels contain plain text. Tests look up the named labels with
`findChild(QLabel, object_name)` and the button box by its Qt type; no additional
object names are required.

### 4.3 Widget hierarchy and sizing

The widget composition follows option B: icon beside the name/version block,
then the description, then the right-aligned button box. Pin the layout hierarchy
as follows; all four content labels and the button box are children of the dialog.

```text
AboutDialog (QDialog)
└── QVBoxLayout
    ├── QHBoxLayout (header)
    │   ├── QLabel (48 × 48 application icon)
    │   └── QVBoxLayout
    │       ├── QLabel#aboutNameLabel
    │       └── QLabel#aboutVersionLabel
    ├── QLabel#aboutDescriptionLabel
    └── QDialogButtonBox
        └── QPushButton (StandardButton.Close)
```

| Property | Required behaviour |
| --- | --- |
| Width | Fixed at 360 Qt logical pixels, making the design's approximately 360 px target concrete: `minimumWidth() == maximumWidth() == width() == 360`, and `sizeHint().width() == 360`. |
| Height | Determined by the layout's content size; no fixed height is imposed (`minimumHeight() < maximumHeight()`), and the dialog sets no `resize()`/`setFixedHeight()` call. |
| Description | Word wrapping disabled so it remains a single line. |
| Size grip | Disabled: `isSizeGripEnabled() is False`. |
| Modality | Modal: `isModal() is True`. Both entry points execute it with `exec()`. |
| Button box | Orientation is `Qt.Orientation.Horizontal`, and after layout every button's left edge lies in the right half of the box (`mapTo(button_box, QPoint(0, 0)).x() > button_box.width() / 2`). |
| Placement | Qt's default dialog placement over the parent; the dialog contains no manual `move()` or geometry code. The testable contract is ownership: `dialog.parentWidget()` is the widget supplied as `parent`, asserted by identity, not by pixel centring. |
| Styling | Uses the application stylesheet and the icon returned by `color_icon()`, called through the module-scope name `ai_manager.ui.about_dialog.color_icon`. The test patches that name with a sentinel `QIcon` and asserts the icon label's pixmap matches it, proving the helper is actually called. |

### 4.4 Close-button result

The standard Close button has `RejectRole`, so the button box emits `rejected`
when it is clicked. The button's own `clicked` signal MUST be connected directly
to `self.accept()`:

```python
button_box.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
```

Clicking Close must end `exec()` with `QDialog.DialogCode.Accepted` and leave
`result() == QDialog.DialogCode.Accepted`. Wiring only
`button_box.accepted.connect(self.accept)` cannot meet this contract. Do not
connect the About button box's `rejected` signal to `self.reject`, which would
introduce a competing result for this click.

## 5. Module `ai_manager.ui.main_window`

### 5.1 Main window title

The current title in `_init_ui()` is
`ai-manager — AI Provider Configuration & Service Controller`. Its exact
replacement template is:

```python
f"ai-manager v{__version__} — AI Provider Configuration & Service Controller"
```

The separator is an em dash (U+2014), surrounded by spaces. Preserve the literal
single `&` in `Configuration & Service Controller`. Window titles are rendered
literally, as documented by `ui/mnemonic.py` and asserted by the existing
mnemonic test; do not call `escape_mnemonic` on this title.

### 5.2 About entry point

Import `AboutDialog` from `ai_manager.ui.about_dialog` at module scope. Add:

```python
def open_about_dialog(self) -> None: ...
```

Each call constructs a fresh `AboutDialog(self)`, calls that instance's `exec()`
exactly once, and discards the return value. There is no cached dialog or shared
instance. The constructor uses the default version from §4.1.

Add the following connection alongside the existing tray connections in
`MainWindow.__init__`:

```python
self.tray_manager.about_requested.connect(self.open_about_dialog)
```

## 6. Module `ai_manager.ui.system_tray`

### 6.1 Signal and action

Add this no-argument signal on `SystemTrayManager`:

```python
about_requested = pyqtSignal()
```

| Member | Contract |
| --- | --- |
| `self._about_action` | The QAction returned when adding `About ai-manager` to `self._context_menu`. |
| Action text | Exactly `About ai-manager`, with no mnemonic marker or ellipsis. |
| Trigger | Connect `_about_action.triggered` to `about_requested.emit`, matching the existing action-to-signal pattern. Each trigger emits one `about_requested` signal. |
| Location | Immediately after `self._settings_action`, before the existing final separator and `self._quit_action`. |

### 6.2 Exact menu order

Immediately after `SystemTrayManager()` construction, the ordered list of
`action.text()` values is exactly the following; empty strings are separators:

1. `"Show ai-manager"`
2. `""`
3. `"Start All Supervised Services"`
4. `"Stop All Supervised Services"`
5. `""`
6. `"⚙ Settings..."`
7. `"About ai-manager"`
8. `""`
9. `"Quit ai-manager"`

The zero-based separator indices are exactly `[1, 4, 7]`; the About action is
index `6`. The existing `update_visibility_action_text(True)` still changes only
the first action to `Hide ai-manager`, and `False` restores `Show ai-manager`.
`is_available()` continues to call `QSystemTrayIcon.isSystemTrayAvailable()` on
each invocation, without caching.

## 7. Module `ai_manager.ui.settings_dialog`

Keep `_build_button_box()` producing the existing horizontal `QDialogButtonBox` with
standard Save and Cancel, `btn_save`/`btn_cancel`, and the accepted/rejected
connections to `_on_save`/`reject` unchanged. Add a footer row that places a new
About button to the left of that box:

```python
def _build_footer(self) -> QHBoxLayout:
    footer = QHBoxLayout()
    self.btn_about = QPushButton("About ai-manager", self)
    footer.addWidget(self.btn_about)
    footer.addStretch(1)
    footer.addWidget(self._build_button_box())
    return footer
```

`_init_ui()` adds `_build_footer()` where it currently adds the button box.

| Element | Required contract |
| --- | --- |
| About control | One `QPushButton`, exposed as `self.btn_about`, text exactly `About ai-manager`. It is a sibling of the button box in the footer row, not a member of the button box. |
| Position | Left-aligned in the footer row; the Save/Cancel button box is right-aligned after an expanding stretch. Horizontal position is therefore independent of the platform style. |
| Button box | Still contains exactly the standard Save and Cancel buttons, unchanged order, texts, `btn_save`/`btn_cancel` aliases, and accepted/rejected wiring. |
| Click behaviour | Construct a fresh `AboutDialog(parent=self)` and call its `exec()` directly from Settings. |
| Ownership | `AboutDialog.parentWidget()` is the Settings dialog, including while Settings is executing modally. Closing About returns control to Settings. |
| Settings effects | Clicking About emits no `settings_saved`, does not accept/reject Settings, and does not call `_on_save` or any desktop-service operation. Pending edits and the caller's settings retain their values. |

Import `AboutDialog` at module scope in `settings_dialog.py`. The parent and
factory call in this section are part of the test seam. Every About click creates
a new instance, including repeated clicks before saving or cancelling Settings.

**Q1 resolution (was open in the draft).** The approved design attributed the
left-of-both position to `QDialogButtonBox.ButtonRole.ActionRole`. A read-only probe
of the real construction under Fusion style showed `addButton(..., ActionRole)`
produces `Save`, `About ai-manager`, `Cancel`, so the role neither implies nor
reliably yields that position. The footer row above replaces the role-based
placement: it keeps the approved visual intent (About separated left of the commit
actions), removes style dependence, and needs no `QDialogButtonBox` internals. The
button-box membership requirement is withdrawn; the position requirement is kept
and is now testable by geometry.

## 8. Error Handling and Edge Cases

Every row from the approved design's edge-case table is normative:

| Situation | Exact required behaviour |
| --- | --- |
| Tray unavailable | About remains reachable through Settings. `SystemTrayManager.is_available()` semantics remain unchanged, with a fresh availability probe on each call. |
| Settings open | About is parented to Settings, remains modal and interactive, and closing it returns control to the still-open Settings dialog. |
| About opened twice | Each entry-point invocation constructs a fresh dialog; no shared state or singleton. |
| Version has a pre-release suffix | Title and About render the version unchanged. The format test intentionally rejects a value such as `0.2.0rc1` under the current release scheme; a future change introducing that scheme must update the format test in the same change. Pre-release support is outside this change. |
| Text with `&` | No new mnemonic-aware text contains a bare ampersand. The About sweep returns `[]`; the main title retains its literal `&`. Existing Settings text continues to store `Save && Apply` and `Desktop && Application Menu`. |
| Wheel build | The wheel's distribution `METADATA` contains `Version:` equal to `ai_manager.__version__`. |

There is no version-read error path: a missing `__version__` causes the importing
module to fail immediately. Do not substitute a guessed value or read installed
distribution metadata. Icon rendering uses the existing `color_icon()` API;
version handling adds no asset, settings, or desktop-service IO.

## 9. Test Plan

### 9.1 Fixtures and seams

Use pytest-qt for Qt tests and the existing headless test setup. Reuse
`make_test_window(qtbot, tmp_path)` in `tests/test_main_window.py` for new window
cases. Use the existing `dialog`, `settings`, and `service` fixtures in
`tests/test_settings_dialog.py`; its `FakeDesktopService` records side effects.
Register new dialogs with `qtbot.addWidget`.

Two distinct seams are required, and a test may not substitute one for the other.

- **Factory seam** (no real modal): patch `ai_manager.ui.main_window.AboutDialog`
  or `ai_manager.ui.settings_dialog.AboutDialog` with fakes. Use distinct fake
  instances for consecutive calls and assert each instance's `exec()` was called.
  This seam proves call count and constructor arguments only. It cannot prove
  ownership, parent identity, or side-effect freedom inside the real dialog.
- **Exec seam** (real constructor): patch only `exec` on the real class
  (`monkeypatch.setattr(AboutDialog, "exec", recorder)`) so the genuine
  `__init__` runs, records `self.parentWidget()`, and returns `1`. Use this seam
  for ownership, nested-Settings, and side-effect assertions.

For version propagation, patch the consumer module attribute
(`monkeypatch.setattr("ai_manager.ui.about_dialog.__version__", "9.8.7")` and the
`main_window` equivalent) and assert the rendered surface follows. Do not patch
`ai_manager.__version__`: from-import binds the name into the consumer module, and
the contract is about consumer-side interpolation.

For the real About Close test, schedule the actual standard Close button's
`click()` with `QTimer.singleShot(0, close_button.click)` before calling
`dialog.exec()`. Assert both its returned code and `dialog.result()`. Calling
`dialog.accept()` in the test would bypass the required wiring and is forbidden.

### 9.2 Normative test cases

Each row names one test function; parameterizations belong to that function.
All tests outside the additions/updates below retain their existing assertions.

| File | Test function | Treatment and precise assertions |
| --- | --- | --- |
| `tests/test_version.py` | `test_version_is_release_triplet` | New. Import `__version__` from `ai_manager`; assert `re.fullmatch(r"^\d+\.\d+\.\d+$", __version__) is not None`. Do not hardcode the current release in the assertion. |
| `tests/test_version.py` | `test_pyproject_derives_version` | New. Parse `Path(__file__).resolve().parents[1] / "pyproject.toml"` with `tomllib`; assert `project["name"] == "ai-manager"`, `"version" not in project`, `project["dynamic"] == ["version"]`, `data["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "ai_manager.__version__"}`, and `project["authors"] == [{"name": "Henry", "email": "wenhepku@gmail.com"}]`. Also assert the untouched declarations survive: `project["description"]`, `project["dependencies"]` (the four pinned entries), `project["optional-dependencies"]["dev"]` (pytest, pytest-qt, respx), `project["scripts"] == {"ai-manager": "ai_manager.main:main"}`, `build-system == {"requires": ["setuptools>=61.0"], "build-backend": "setuptools.build_meta"}`, and `data["tool"]["setuptools"]["package-data"]["ai_manager"] == ["resources/icons/*.svg"]`. |
| `tests/test_version.py` | `test_version_literal_is_static_string` | New. Read `src/ai_manager/__init__.py` with `ast.parse`. Assert exactly one module-level `ast.Assign` targets the name `__version__`, its `value` is `ast.Constant` with `isinstance(value.value, str)`, and no other assignment to `__version__` exists anywhere in the module. This fails for `"".join(...)`, f-strings, and ternaries even when the resulting string is identical. |
| `tests/test_version.py` | `test_version_init_has_no_imports` | New. `ast.parse` of `src/ai_manager/__init__.py`; assert no `ast.Import` or `ast.ImportFrom` node exists in the module body. This encodes the import-purity contract (no metadata lookup, no IO at import). |
| `tests/test_version.py` | `test_version_consumers_import_the_symbol` | New. For each of `src/ai_manager/ui/main_window.py` and `src/ai_manager/ui/about_dialog.py`: `ast.parse` and assert an `ast.ImportFrom` with `module == "ai_manager"` and an alias named `__version__` exists; assert `re.search(r"\d+\.\d+\.\d+", source)` is `None` (no second version literal); and assert no `Import`/`ImportFrom` of `importlib`, `importlib.metadata`, `subprocess`, `platform`, or `tomllib` appears. This fails a hardcoded UI default or a metadata-based read. |
| `tests/test_about_dialog.py` | `test_about_dialog_content_and_object_names` | New. Construct with the default version; assert title `About ai-manager`; exactly one QLabel for each of the three specified object names; their texts equal `ai-manager`, `f"Version {__version__}"`, and `Desktop administration GUI for local AI backends`; all four content labels have no buddy; exactly one remaining content label has empty text and a non-null pixmap of device-independent size 48 × 48. |
| `tests/test_about_dialog.py` | `test_about_dialog_hierarchy_and_geometry` | New. Assert the layout types and item order in §4.3; the header's first item is the icon label and its second is the two-label vertical layout; all four labels and the sole button box have the dialog as parent widget. Assert `minimumWidth() == maximumWidth() == width() == 360`, `sizeHint().width() == 360`, `minimumHeight() < maximumHeight()`, description `wordWrap() is False`, `isModal() is True`, and `isSizeGripEnabled() is False`. Assert the button box `orientation() == Qt.Orientation.Horizontal` and, after `show()` plus layout activation, that every button's left edge lies in the box's right half. |
| `tests/test_about_dialog.py` | `test_about_dialog_uses_color_icon` | New. Patch `ai_manager.ui.about_dialog.color_icon` with a function returning a sentinel `QIcon` built from a 1 × 1 magenta `QPixmap`. Construct the dialog and assert the icon label's pixmap's centre pixel is magenta. This fails an implementation that hardcodes a different icon or a null pixmap. |
| `tests/test_about_dialog.py` | `test_about_dialog_version_propagates_from_source` | New. `monkeypatch.setattr("ai_manager.ui.about_dialog.__version__", "9.8.7")`; construct `AboutDialog()` with no `version` argument; assert `aboutVersionLabel.text() == "Version 9.8.7"`. This fails a default-argument binding that froze the value at import time. |
| `tests/test_about_dialog.py` | `test_about_dialog_parent_is_supplied_widget` | New. Construct `AboutDialog(parent=sentinel_widget)` and assert `dialog.parentWidget() is sentinel_widget`. This fails `super().__init__(None)`, which the factory-mock tests cannot detect. |
| `tests/test_about_dialog.py` | `test_about_dialog_accepts_injected_version` | New. Parameterize `version` with `"9.8.7"` and `"0.2.0rc1"`; construct `AboutDialog(version=version)` and assert `findChild(QLabel, "aboutVersionLabel").text() == f"Version {version}"`. This does not change the application's release scheme. |
| `tests/test_about_dialog.py` | `test_close_button_accepts_dialog` | New. Assert the only button is standard Close, its text is `Close`, and `buttonRole(close_button) == QDialogButtonBox.ButtonRole.RejectRole`. Schedule its click as in §9.1; assert `exec()` and `result()` both equal `QDialog.DialogCode.Accepted`. |
| `tests/test_about_dialog.py` | `test_about_dialog_has_no_unescaped_ampersands` | New. Reuse `find_unescaped_ampersand_sinks` from `tests/test_mnemonic.py`; construct the real About dialog and assert `find_unescaped_ampersand_sinks(dialog) == []`. Also assert its standard Close button exists so the sweep traverses a mnemonic-aware widget. |
| `tests/test_main_window.py` | `test_main_window_title_includes_version` | New. Assert `window.windowTitle() == f"ai-manager v{__version__} — AI Provider Configuration & Service Controller"`, `f"v{__version__}" in window.windowTitle()`, and `"&" in window.windowTitle()`. |
| `tests/test_main_window.py` | `test_title_propagates_patched_source_version` | New. After importing `ai_manager.ui.main_window`, `monkeypatch.setattr(main_window_module, "__version__", "9.8.7")`, then construct the window and assert the title equals `"ai-manager v9.8.7 — AI Provider Configuration & Service Controller"`. This fails a hardcoded title string even when the default value matches today's release. |
| `tests/test_main_window.py` | `test_open_about_dialog_constructs_fresh_modal` | New. Patch the module's About factory with two distinct fakes; call `window.open_about_dialog()` twice. Assert factory `call_args_list == [call(window), call(window)]` and each fake's `exec.assert_called_once_with()`. |
| `tests/test_main_window.py` | `test_tray_about_request_opens_about_dialog` | New. Trigger `window.tray_manager._about_action`; assert the patched About factory was called once with positional `window`, and that instance's `exec()` was called once with no arguments. Exercise the real QAction-to-signal-to-window connection. |
| `tests/test_system_tray.py` | `test_context_menu_order_and_structure` | Update. Replace the eight-entry expected text list with the exact nine-entry list in §6.2. Assert separator indices are exactly `[1, 4, 7]` and `actions[6] is manager._about_action`; remove the old assertion that index `6` is a separator. |
| `tests/test_system_tray.py` | `test_menu_action_emits_expected_signal` | Update. Add `("_about_action", "about_requested")` to the existing parameter list. Trigger the selected action under `qtbot.waitSignal(getattr(manager, signal_name), timeout=1000)`; also record emissions and assert exactly one no-argument emission for the added About case. |
| `tests/test_system_tray.py` | `test_update_visibility_action_text` | Retain, extended. Snapshot the full ordered list of `action.text()` values; after `update_visibility_action_text(True)` assert index `0` is `"Hide ai-manager"` **and** indices `1..8` are identical to the snapshot; repeat for `False` restoring `"Show ai-manager"`. This fails a change that reorders or retitles other actions while toggling visibility. |
| `tests/test_system_tray.py` | `test_is_available_is_not_cached` | Retain. Set availability False, then True on the same manager; assert `is_available() is False`, then `is_available() is True`. |
| `tests/test_settings_dialog.py` | `test_about_button_sits_left_of_action_buttons` | New. Assert `dialog.btn_about.text() == "About ai-manager"`, it is a `QPushButton` whose parent widget is the dialog, and it is **not** in `button_box.buttons()`. Assert the footer layout item order is exactly About button, stretch, button box, and that the button box still maps `btn_save`/`btn_cancel` to the standard Save/Cancel buttons with texts `Save && Apply` and `Cancel`. Show the dialog, activate layouts, then assert separately for both: `btn_about.mapTo(dialog, QPoint(0, 0)).x() + btn_about.width() <= btn_x.mapTo(dialog, QPoint(0, 0)).x()` for `btn_x` in `(btn_save, btn_cancel)`. |
| `tests/test_settings_dialog.py` | `test_about_click_uses_real_dialog_parented_to_settings` | New. Use the exec seam: patch `ai_manager.ui.settings_dialog.AboutDialog.exec` with a recorder returning `1`; do not patch the factory. Before clicking, set `dlg.chk_autostart.setChecked(True)` as a pending edit and snapshot all of: `settings.model_dump()`, `dlg.settings.model_dump()`, the five editable control values (three checkboxes, theme, poll interval), and the service's `autostart_calls`, `install_calls`, `remove_calls`. Show Settings, click `btn_about`. After the real constructor and `exec()` return, assert the real `AboutDialog` was constructed with `parent` identity equal to the Settings dialog, the recorded instance's `parentWidget()` is that same dialog, `exec()` ran once, Settings is still visible and not accepted, `settings_saved` was not emitted, **every snapshot above is unchanged**, and `dlg.chk_autostart.isChecked() is True`. This fails `super().__init__(None)`, any About constructor that mutates the parent's settings model or controls, and any About implementation that touches the desktop service. |
| `tests/test_settings_dialog.py` | `test_about_button_opens_about_without_saving` | New. Parameterize tray availability True/False using `mock_tray_available`, set it before constructing Settings, and use the fake desktop service. Set `dlg.chk_autostart.setChecked(True)` as a pending edit; snapshot `settings.model_dump()`, `dlg.settings.model_dump()`, the five editable control values (three checkboxes, theme, poll interval), and the service's `autostart_calls`, `install_calls`, and `remove_calls`. Click the About button with the module factory patched. Assert factory called once with `parent=dlg`, its instance's `exec()` called once, `settings_saved` was not emitted, Settings accepted/rejected signals were not emitted, all snapshots are unchanged, and `dlg.chk_autostart.isChecked() is True`. |
| `tests/test_settings_dialog.py` | `test_about_button_constructs_fresh_dialog_each_time` | New. Click About twice with the factory returning two distinct fakes; assert `call_args_list == [call(parent=dialog), call(parent=dialog)]`, each fake's `exec()` called once, and no `settings_saved` emission. |
| `tests/test_settings_dialog.py` | `test_save_emits_settings_and_syncs_autostart` | Retain. Save still emits the expected `UserSettings`, records `[(True, True)]` for autostart, and leaves `result() == 1` (Accepted). |
| `tests/test_settings_dialog.py` | `test_cancel_rejects_without_saving` | Retain. Cancel leaves `result() == 0` (Rejected) and `service.autostart_calls == []`. |
| `tests/test_mnemonic.py` | `test_settings_dialog_has_no_unescaped_ampersands` | Retain unchanged. Assert `find_unescaped_ampersand_sinks(dlg) == []`, `dlg.btn_save.text() == "Save && Apply"`, and the group titles contain `Desktop && Application Menu`. The Settings sweep includes the new About button automatically. |
| `tests/test_mnemonic.py` | `test_main_window_has_no_unescaped_ampersands` | Retain unchanged. Assert `find_unescaped_ampersand_sinks(window) == []`, nonempty QAbstractButton and QMenu descendants, and `"&" in window.windowTitle()`. The tray-menu sweep includes the new About action automatically. |
| `tests/test_readme_documents_version.py` | `test_readme_documents_version_display` | New. Read `README.md` from the repository root and assert it contains both exact sentences: `- **Version Display**: The version appears in the window title and in the About dialog (tray menu or Settings).` and ``Bump the version only in `src/ai_manager/__init__.py`; packaging metadata derives from it. Re-run the editable install after a bump.`` |

Three existing tray tests change: `test_context_menu_order_and_structure`
(Update: nine entries, separators, About identity),
`test_menu_action_emits_expected_signal` (Update: add the `_about_action` /
`about_requested` parameter case), and `test_update_visibility_action_text`
(Retain, extended: full-list snapshot). Add the named cases to the existing
main-window and Settings modules; do not weaken existing mnemonic, Save, Cancel,
or availability assertions. The version-format regex is exactly
`^\d+\.\d+\.\d+$`.

The plan contains exactly **one non-pytest verification**: the §10.3 wheel build
and metadata inspection, executed as a verification step after the suite passes.
The README requirement is a pytest case
(`test_readme_documents_version_display`), not a manual check.

## 10. Acceptance Criteria

### 10.1 Mechanical checklist

- [ ] `src/ai_manager/__init__.py` remains the sole authored application-version source, `__version__ = "0.1.4"`; the literal is an `ast.Constant` string; the module imports nothing; `main_window.py` and `about_dialog.py` import the symbol and contain no version literal and no metadata/subprocess/platform imports.
- [ ] Changing the consumer module's `__version__` changes both rendered surfaces (title and About label); no frozen default-argument binding exists.
- [ ] Parsed `pyproject.toml` matches §2, has no static project version, derives the version through `ai_manager.__version__`, and preserves every unchanged declaration listed in the `test_pyproject_derives_version` row.
- [ ] The author name/email are exactly `Henry` / `wenhepku@gmail.com`.
- [ ] About's constructor, named labels, icon dimensions and icon provenance, layout hierarchy, horizontal right-aligned button box, fixed width, size hint, layout-driven height, modal state, and Close result satisfy §4 and their test rows.
- [ ] A real `AboutDialog` constructed with a parent reports that exact `parentWidget()`; replacing the parent with `None` fails a named test.
- [ ] The main window title equals the §5.1 template and retains its literal single ampersand.
- [ ] Triggering the tray About action emits one signal and executes one fresh About dialog parented to MainWindow.
- [ ] The tray has exactly nine menu entries with separator indices `[1, 4, 7]` and the About action at index `6`.
- [ ] The Settings About button is a left-aligned footer push button, separate from the Save/Cancel button box, in the footer order About/stretch/button box, positioned left of **both** Save and Cancel; clicking it constructs the real `AboutDialog` with `parent=dialog`, leaves Settings open, and leaves settings and desktop-service counters unchanged.
- [ ] The existing main-window and Settings mnemonic sweeps and the new About sweep return `[]` with their non-vacuity assertions intact.
- [ ] README contains the two exact sentences specified in §9.2, verified by `test_readme_documents_version_display`.
- [ ] Toggling tray visibility leaves every action except index `0` unchanged in text and order.
- [ ] Q1 is resolved by the footer-row construction in §7; the geometry test passes under the project's Qt style.
- [ ] Every new/updated test in §9 and the full existing test suite pass using §10.2.
- [ ] A newly built wheel's `METADATA` version equals the imported source version using §10.3.

### 10.2 Full-suite command

Run from the implementation worktree root with the project test dependencies
available:

```bash
AI_WORKSPACE_ROOT=/data/home/guest/Development/ai PYTHONPATH=src pytest tests/
```

Require exit status `0` and no failing tests. The pinned `AI_WORKSPACE_ROOT`
prevents the worktree cwd from changing the e2e workspace selection. The design
records 649 passing baseline tests at `e02edae`; the delivery branch was re-baselined from `3b1e5b1` to `e02edae` (`0.1.4`) after that release landed, so new tests increase the total and both figures are historical evidence rather than a required final count.

### 10.3 Wheel metadata verification

Build with the exact command approved in the design:

```bash
python -m pip wheel --no-deps --no-build-isolation -w dist .
```

Require exit status `0`. For this unchanged release the produced wheel is
`dist/ai_manager-0.1.4-py3-none-any.whl`. Inspect that exact wheel, rather than an
arbitrary older archive from `dist`, with the following verification command:

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

Both the build and metadata check must pass. This verifies packaging's derived
value independently of the UI tests without adding a runtime metadata read.

## 11. Open Questions

None. Q1 (Settings About-button placement) is resolved in §7: the button is a
left-aligned push button in a footer row beside the unchanged Save/Cancel button
box, because `ButtonRole.ActionRole` inside the box produced `Save | About | Cancel`
under Fusion and cannot express a style-independent left-of-both position.
