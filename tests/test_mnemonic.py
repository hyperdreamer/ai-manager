"""Tests for ampersand/mnemonic escaping in Qt widget text.

Qt silently *removes* a single ``&`` from the text of mnemonic-aware widgets
(buttons, group-box titles, tab labels, menu actions and labels with a buddy)
and underlines the following character instead. ``escape_mnemonic`` is the
documented way to make such text render the literal character.

Besides unit-testing the helper, these tests pin the Qt behaviour itself
(so the helper cannot become a silent no-op) and sweep the real dialogs for
widgets that still hold an unescaped ``&``.
"""

import re

import pytest
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QGroupBox,
    QLabel,
    QMenu,
    QPushButton,
    QTabWidget,
    QToolButton,
)

from ai_manager.config.models import ThemeMode
from ai_manager.ui.mnemonic import escape_mnemonic
from ai_manager.ui.theme import get_stylesheet

# A single '&' that is not part of an escaped '&&' pair.
_UNESCAPED_AMPERSAND = re.compile(r"(?<!&)&(?!&)")

# Widgets are measured under the stylesheet the application actually renders
# with: it changes widget geometry (notably the fusion group-box frame), and
# applying it per widget keeps the measurement independent of test order.
_TEST_STYLESHEET = get_stylesheet(ThemeMode.DARK)


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------
def test_escape_mnemonic_doubles_every_ampersand():
    assert escape_mnemonic("Save & Apply") == "Save && Apply"
    assert escape_mnemonic("A&B&C") == "A&&B&&C"
    assert escape_mnemonic("qwen&co/7b-instruct") == "qwen&&co/7b-instruct"


def test_escape_mnemonic_is_a_noop_without_ampersands():
    assert escape_mnemonic("Plain text") == "Plain text"
    assert escape_mnemonic("") == ""


def test_escape_mnemonic_expects_raw_text():
    # Documents the contract: callers pass raw text, never pre-escaped text.
    assert escape_mnemonic("A&&B") == "A&&&&B"


def _text_ink_width(widget, set_text, text: str, qtbot) -> int:
    """Width in pixels of the glyphs ``text`` actually paints in ``widget``.

    Measured by diffing two real renders (empty text vs ``text``) so the result
    is independent of the active palette -- a lightness threshold would break
    once another test installs the dark theme.
    """
    widget.setStyleSheet(_TEST_STYLESHEET)
    widget.resize(320, 90)
    qtbot.addWidget(widget)
    widget.show()

    set_text("")
    QApplication.processEvents()
    blank = widget.grab().toImage()

    set_text(text)
    QApplication.processEvents()
    painted = widget.grab().toImage()

    height = blank.height()
    columns = [
        x
        for x in range(blank.width())
        # Column strips compare in C++, which keeps this far cheaper than a
        # per-pixel Python loop.
        if blank.copy(x, 0, 1, height) != painted.copy(x, 0, 1, height)
    ]
    return (max(columns) - min(columns) + 1) if columns else 0


# ---------------------------------------------------------------------------
# The Qt behaviour the helper exists for
# ---------------------------------------------------------------------------
def _make_widget(kind: str):
    """Build the widget under test and a setter for its mnemonic text."""
    if kind == "QPushButton":
        button = QPushButton()
        return button, button.setText
    if kind == "QToolButton":
        button = QToolButton()
        return button, button.setText
    if kind == "QCheckBox":
        box = QCheckBox()
        return box, box.setText
    if kind == "QGroupBox":
        group = QGroupBox()
        return group, group.setTitle
    raise AssertionError(f"unsupported widget kind: {kind}")


@pytest.mark.parametrize("kind", ["QPushButton", "QToolButton", "QCheckBox", "QGroupBox"])
def test_single_ampersand_is_swallowed_by_mnemonic_widgets(qtbot, kind):
    """An unescaped '&' loses a glyph; the escaped form renders it."""

    def width(body: str) -> int:
        widget, set_text = _make_widget(kind)
        return _text_ink_width(widget, set_text, "X" + body + "Y", qtbot)

    escaped, unescaped, plain = width("&&"), width("&"), width("")

    # Falsifiable: if Qt rendered '&' literally, the unescaped form would be a
    # full glyph wider than the plain form. Mnemonic stripping leaves at most
    # the underline behind, so the two margins must stay distinguishable.
    assert escaped - unescaped >= 5, "escaped '&' should add a glyph's width"
    assert unescaped - plain < escaped - unescaped, "single '&' should be swallowed"


def test_plain_label_is_not_a_mnemonic_sink(qtbot):
    """A QLabel without a buddy renders '&' literally, so it must not be escaped."""
    literal, plain, doubled = QLabel("X&Y"), QLabel("XY"), QLabel("X&&Y")
    for label in (literal, plain, doubled):
        qtbot.addWidget(label)

    assert literal.sizeHint().width() > plain.sizeHint().width()
    assert doubled.sizeHint().width() > literal.sizeHint().width()


# ---------------------------------------------------------------------------
# Sweep helper + regression sweeps of the shipped UI
# ---------------------------------------------------------------------------
def find_unescaped_ampersand_sinks(root) -> list:
    """Return ``(kind, objectName, text)`` for mnemonic widgets holding a bare '&'."""
    offenders = []
    for widget in root.findChildren(QAbstractButton):
        if _UNESCAPED_AMPERSAND.search(widget.text()):
            offenders.append((type(widget).__name__, widget.objectName(), widget.text()))
    for group in root.findChildren(QGroupBox):
        if _UNESCAPED_AMPERSAND.search(group.title()):
            offenders.append(("QGroupBox", group.objectName(), group.title()))
    for tabs in root.findChildren(QTabWidget):
        for index in range(tabs.count()):
            if _UNESCAPED_AMPERSAND.search(tabs.tabText(index)):
                offenders.append(("QTabWidget", tabs.objectName(), tabs.tabText(index)))
    for menu in root.findChildren(QMenu):
        for action in menu.actions():
            if _UNESCAPED_AMPERSAND.search(action.text()):
                offenders.append(("QAction", menu.objectName(), action.text()))
    for label in root.findChildren(QLabel):
        if label.buddy() is not None and _UNESCAPED_AMPERSAND.search(label.text()):
            offenders.append(("QLabel(buddy)", label.objectName(), label.text()))
    return offenders


def test_sweep_helper_detects_unescaped_ampersands(qtbot):
    """Guards the sweeps below from becoming vacuous."""
    holder = QGroupBox("Container")
    qtbot.addWidget(holder)
    QPushButton("Install & Update", holder)
    QGroupBox("Desktop & Menu", holder)
    QPushButton("Install && Update", holder)
    QLabel("A & B", holder)  # no buddy: legitimately literal, must not be flagged

    found = find_unescaped_ampersand_sinks(holder)
    texts = {text for _, _, text in found}

    assert "Install & Update" in texts
    assert "Desktop & Menu" in texts
    assert "Install && Update" not in texts
    assert "A & B" not in texts


def test_settings_dialog_has_no_unescaped_ampersands(qtbot):
    from ai_manager.config.models import UserSettings
    from ai_manager.ui.settings_dialog import SettingsDialog

    class _StubDesktopService:
        def is_desktop_shortcut_installed(self) -> bool:
            return True

        def install_desktop_shortcut(self) -> bool:
            return True

        def remove_desktop_shortcut(self) -> bool:
            return True

        def set_autostart(self, enabled: bool, start_minimized: bool = False) -> bool:
            return True

    dlg = SettingsDialog(UserSettings(), _StubDesktopService())
    qtbot.addWidget(dlg)

    assert find_unescaped_ampersand_sinks(dlg) == []
    # The two widgets that originally showed a stray "_" glyph instead of '&'.
    assert dlg.btn_save.text() == "Save && Apply"
    assert "Desktop && Application Menu" in [
        group.title() for group in dlg.findChildren(QGroupBox)
    ]


def test_main_window_has_no_unescaped_ampersands(qtbot, tmp_path, monkeypatch):
    """Sweep the whole window, including the system-tray context menu."""
    import shutil
    from pathlib import Path

    from ai_manager.config.models import UserSettings
    from ai_manager.ui import main_window as main_window_module
    from ai_manager.ui.main_window import MainWindow

    fixtures_dir = Path(__file__).parent / "fixtures"
    for app_id in ["ai-grammar", "textkit", "yt2txt"]:
        (tmp_path / app_id / "backend").mkdir(parents=True)
    shutil.copy2(
        fixtures_dir / "ai_grammar_config.yaml",
        tmp_path / "ai-grammar" / "backend" / "config.yaml",
    )
    shutil.copy2(
        fixtures_dir / "textkit_unified_config.yaml",
        tmp_path / "textkit" / "backend" / "config.yaml",
    )
    shutil.copy2(
        fixtures_dir / "yt2txt_config.yaml",
        tmp_path / "yt2txt" / "backend" / "config.yaml",
    )
    monkeypatch.setattr(main_window_module, "load_user_settings", lambda: UserSettings())
    monkeypatch.setattr(main_window_module, "save_user_settings", lambda s: None)

    window = MainWindow(workspace_root=tmp_path)
    qtbot.addWidget(window)

    assert find_unescaped_ampersand_sinks(window) == []
    # Guard the sweep against silently walking an empty tree.
    assert window.findChildren(QAbstractButton)
    assert window.findChildren(QMenu), "system-tray context menu should be found"
    # The window title is drawn by the window manager and stays literal.
    assert "&" in window.windowTitle()


def test_app_detail_view_escapes_dynamic_model_names(qtbot):
    from pathlib import Path

    from ai_manager.config.app_registry import get_managed_apps
    from ai_manager.ui.app_detail_view import AppDetailView

    apps = get_managed_apps(Path("/tmp"))
    view = AppDetailView(apps["textkit"])
    qtbot.addWidget(view)

    # Provider model names are arbitrary text fed straight into QToolButtons.
    view.set_available_models(["plain", "qwen&co/7b", "a&&b"])

    assert find_unescaped_ampersand_sinks(view) == []

    chips = [
        view._chips_layout.itemAt(i).widget()
        for i in range(view._chips_layout.count())
        if view._chips_layout.itemAt(i).widget() is not None
    ]
    assert [chip.text() for chip in chips] == ["plain", "qwen&&co/7b", "a&&&&b"]
    # Escaping is display-only: clicking a chip still applies the raw name.
    chips[1].click()
    assert view.get_current_draft().model == "qwen&co/7b"
