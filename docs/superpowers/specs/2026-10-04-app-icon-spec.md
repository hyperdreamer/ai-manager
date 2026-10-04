# Technical Specification: Application Icon Set (Tray, Window, Launcher)

Source of truth: `docs/superpowers/specs/2026-10-04-app-icon-design.md` (the approved design document).
This specification is implementable without reading that document; where the
design document and this specification appear to diverge, the design document
wins and the divergence is recorded in section 13.

---

## 1. Scope and Non-Goals

### 1.1 Scope

1. Add two packaged SVG assets under `src/ai_manager/resources/icons/`:
   a full-colour icon and a two-token symbolic icon template.
2. Add a Qt-free asset accessor module (`ai_manager.resources.assets`) that
   resolves the packaged assets by a `kind` string.
3. Add a Qt icon-rendering module (`ai_manager.ui.icons`) that rasterises the
   assets with `QSvgRenderer` into `QIcon`s at a fixed matrix of sizes and
   device-pixel ratios, and computes a palette-driven two-tone tray tint.
4. Install the full-colour icon as the `QApplication` window icon in
   `main.py`.
5. Replace the tray icon source: `SystemTrayManager._apply_icon()` now requests
   the palette-tinted symbolic icon and re-tints on `QApplication.paletteChanged`.
6. Point the generated `.desktop` entry's `Icon=` at the absolute path of the
   colour asset, falling back to the theme name `applications-development`.
7. Declare the SVG files as package data in `pyproject.toml`.
8. Add `tests/test_icons.py` and extend `tests/test_desktop_integration.py`
   and `tests/test_system_tray.py`.

### 1.2 Non-Goals

- No icon theme installation (`hicolor`), no themed-name registration.
- No light/dark variants of the colour asset.
- No use of `QIcon.fromTheme()` or Plasma symbolic recolouring.
- No gradients, filters, masks or clipping in the assets (SVG Tiny 1.2 profile).
- No rendering of sizes outside `SIZES`; Qt scales from the nearest listed size.
- No fix to the pre-existing `pyproject.toml` `idn-email` / setuptools 81 defect.
- No rewrite of an already-installed `~/.local/share/applications/ai-manager.desktop`
  on startup.
- No change to `app.setDesktopFileName(...)`, `StartupWMClass`, or window
  grouping semantics.

---

## 2. Exact File Inventory

| Path | Action | Purpose |
|---|---|---|
| `src/ai_manager/resources/__init__.py` | Create (empty, 0 bytes) | Makes `resources` a real importable subpackage for `importlib.resources`. |
| `src/ai_manager/resources/assets.py` | Create | Qt-free `kind -> file` resolver and byte/path accessors. |
| `src/ai_manager/resources/icons/ai-manager.svg` | Create (byte-exact) | Full-colour icon. |
| `src/ai_manager/resources/icons/ai-manager-symbolic.svg` | Create (byte-exact) | Two-token symbolic template (`__GLYPH__`, `__HALO__`). |
| `src/ai_manager/ui/icons.py` | Create | `QSvgRenderer`-based icon builders, tray tint, window-icon helper. |
| `src/ai_manager/main.py` | Modify | Call `configure_app_icon(app)` right after `QApplication` construction. |
| `src/ai_manager/ui/system_tray.py` | Modify | Use `tray_icon(app)`, fall back to `SP_ComputerIcon`, re-tint on palette change. |
| `src/ai_manager/services/desktop_integration.py` | Modify | `Icon=` becomes the colour asset path, with theme-name fallback. |
| `tests/test_icons.py` | Create | All icon-pipeline tests. |
| `tests/test_desktop_integration.py` | Modify | Replace stale `Icon=` assertion; add fallback test. |
| `tests/test_system_tray.py` | Modify | Add non-null tray-icon and palette re-tint tests. |
| `pyproject.toml` | Modify | Add `[tool.setuptools.package-data]`. |

No other file is created or modified. In particular, `resources/icons/` is a
**data directory**, not a package: do not add `resources/icons/__init__.py`.

---

## 3. Icon Assets (`src/ai_manager/resources/icons/`)

Both files are UTF-8, use `\n` (LF) line endings, and have **no trailing
newline**. The colour file is exactly 492 bytes; the symbolic file is exactly
870 bytes. Reproduce the blocks below literally.

### 3.1 `ai-manager.svg` (full colour, no tokens)

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
<g stroke="#3B82F6" stroke-width="1.5" stroke-linecap="round">
<line x1="12" y1="13.5" x2="12.00" y2="6.40"/>
<line x1="12" y1="13.5" x2="5.85" y2="17.05"/>
<line x1="12" y1="13.5" x2="18.15" y2="17.05"/>
</g>
<g fill="#60A5FA">
<circle cx="12.00" cy="6.40" r="2.0"/>
<circle cx="5.85" cy="17.05" r="2.0"/>
<circle cx="18.15" cy="17.05" r="2.0"/>
</g>
<circle cx="12" cy="13.5" r="3.5" fill="#3B82F6"/></svg>
```

### 3.2 `ai-manager-symbolic.svg` (two-token template)

The file is **never parsed unsubstituted**. `_render` replaces the byte
sequences `__HALO__` and `__GLYPH__` with lowercase `#rrggbb` strings before
constructing `QSvgRenderer`.

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
<g stroke="__HALO__" stroke-width="3.1" stroke-linecap="round">
<line x1="12" y1="13.5" x2="12.00" y2="6.40"/>
<line x1="12" y1="13.5" x2="5.85" y2="17.05"/>
<line x1="12" y1="13.5" x2="18.15" y2="17.05"/>
</g>
<g fill="__HALO__">
<circle cx="12.00" cy="6.40" r="2.8"/>
<circle cx="5.85" cy="17.05" r="2.8"/>
<circle cx="18.15" cy="17.05" r="2.8"/>
<circle cx="12" cy="13.5" r="4.3"/>
</g>
<g stroke="__GLYPH__" stroke-width="1.5" stroke-linecap="round">
<line x1="12" y1="13.5" x2="12.00" y2="6.40"/>
<line x1="12" y1="13.5" x2="5.85" y2="17.05"/>
<line x1="12" y1="13.5" x2="18.15" y2="17.05"/>
</g>
<g fill="__GLYPH__">
<circle cx="12.00" cy="6.40" r="2.0"/>
<circle cx="5.85" cy="17.05" r="2.0"/>
<circle cx="18.15" cy="17.05" r="2.0"/>
<circle cx="12" cy="13.5" r="3.5"/></g></svg>
```

Colour roles (informative): hub and links `#3B82F6`, satellites `#60A5FA`. The
halo layer is drawn first and is geometrically larger (`HUB + HALO = 4.3`,
`SAT + HALO = 2.8`, links `STROKE + 2*HALO = 3.1`); the glyph layer is drawn on
top.

---

## 4. Resources Package

### 4.1 `src/ai_manager/resources/__init__.py`

Create the file **empty** (zero bytes). It exists solely to make `resources` a
real subpackage so `importlib.resources.files("ai_manager.resources")` works
from a source checkout (`PYTHONPATH=src`) and from an editable install. Do not
add a docstring or imports.

### 4.2 `src/ai_manager/resources/assets.py`

Write exactly:

```python
"""Qt-free access to the packaged icon assets.

Both public helpers never raise for an unavailable resource: they return
``None`` so callers such as the ``.desktop`` entry generator stay valid when
an asset is missing. An unknown ``kind`` is a programming error and raises
``ValueError`` immediately instead of silently defaulting.
"""

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

_TABLE: dict[str, str] = {
    "color": "ai-manager.svg",
    "symbolic": "ai-manager-symbolic.svg",
}

_PACKAGE = "ai_manager.resources"
_ICON_DIR = "icons"


def _filename(kind: str) -> str:
    try:
        return _TABLE[kind]
    except KeyError:
        raise ValueError(f"unknown icon asset kind: {kind!r}") from None


def _traversable(kind: str) -> Traversable:
    return resources.files(_PACKAGE).joinpath(_ICON_DIR, _filename(kind))


def asset_bytes(kind: str) -> bytes | None:
    """Raw bytes of a packaged icon asset, or ``None`` when unavailable."""
    try:
        return _traversable(kind).read_bytes()
    except (ModuleNotFoundError, OSError):
        return None


def asset_path(kind: str) -> Path | None:
    """Filesystem path of a packaged icon asset, or ``None`` when unavailable."""
    try:
        path = Path(str(_traversable(kind)))
    except (ModuleNotFoundError, OSError):
        return None
    return path if path.is_file() else None
```

Contract notes:

- `_TABLE` is the single `kind -> filename` map. There are exactly two valid
  kinds: `"color"` and `"symbolic"`.
- An unknown `kind` raises `ValueError` from `_filename` for **both**
  `asset_bytes` and `asset_path`; `ValueError` is deliberately not caught by the
  `except (ModuleNotFoundError, OSError)` clauses.
- `asset_path` returns `None` unless the resolved path `is_file()`. Zipped
  installs are out of scope (the generated `.desktop` entry already requires a
  real on-disk checkout for its absolute `Exec=`/`Path=` fields).
- No Qt import is permitted in this module.

---

## 5. Icon Rendering Module (`src/ai_manager/ui/icons.py`)

Write exactly:

```python
"""Application icon rendering for ai-manager (colour, symbolic, tray).

The shipped SVGs are rendered with :class:`QSvgRenderer`, which implements the
**SVG Tiny 1.2** profile. Gradients, filters, masks and clipping degrade
silently under that profile, so the assets deliberately use only paths, lines,
circles and solid fills. Future edits must not reach for unsupported features.

Rendering is done here rather than through ``QIcon(path)`` because it lets us
rasterise an exact size, substitute the symbolic tokens with a deterministic
two-tone palette, and attach a device-pixel-ratio to each pixmap.

``assets`` is imported as a module and its helpers are called as attributes at
call time (never bound to local names) so the missing/malformed-asset tests can
monkeypatch ``ai_manager.resources.assets.asset_bytes``.
"""

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPalette, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

from ai_manager.resources import assets

SIZES: tuple[int, ...] = (16, 22, 24, 32, 48, 64, 128, 256)
DEVICE_PIXEL_RATIOS: tuple[float, ...] = (1.0, 2.0)

_WCAG_CUTOFF = 0.03928
_WCAG_GAMMA = 2.4


def _channel_luminance(component: int) -> float:
    c = component / 255.0
    if c <= _WCAG_CUTOFF:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** _WCAG_GAMMA


def _relative_luminance(color: QColor) -> float:
    """WCAG 2.x relative luminance of an sRGB colour."""
    return (
        0.2126 * _channel_luminance(color.red())
        + 0.7152 * _channel_luminance(color.green())
        + 0.0722 * _channel_luminance(color.blue())
    )


def _contrast(a: QColor, b: QColor) -> float:
    """WCAG 2.x contrast ratio (1.0 .. 21.0)."""
    la = _relative_luminance(a)
    lb = _relative_luminance(b)
    lighter, darker = (la, lb) if la >= lb else (lb, la)
    return (lighter + 0.05) / (darker + 0.05)


def _opposite(glyph: QColor) -> QColor:
    return QColor("#ffffff") if glyph.lightness() < 128 else QColor("#1c1c1c")


def _render(
    kind: str,
    px: int,
    device_pixel_ratio: float,
    glyph: QColor | None,
    halo: QColor | None,
) -> QPixmap | None:
    """Rasterise ``kind`` at ``px`` physical pixels, or ``None`` on failure."""
    data = assets.asset_bytes(kind)
    if data is None:
        return None

    if kind == "symbolic":
        if glyph is None or halo is None:
            raise ValueError("symbolic render requires both glyph and halo colours")
        data = data.replace(b"__HALO__", halo.name().encode("ascii"))
        data = data.replace(b"__GLYPH__", glyph.name().encode("ascii"))

    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        return None

    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()

    if QGuiApplication.instance() is None:
        return None

    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    return pixmap


def color_icon() -> QIcon:
    """Full-colour window/launcher icon, or a null ``QIcon`` on failure."""
    icon = QIcon()
    for size in SIZES:
        for dpr in DEVICE_PIXEL_RATIOS:
            pixmap = _render("color", int(size * dpr), dpr, None, None)
            if pixmap is not None:
                icon.addPixmap(pixmap)
    return icon


def symbolic_icon(glyph: QColor, halo: QColor) -> QIcon:
    """Two-tone tray icon from the symbolic template, or a null ``QIcon``."""
    icon = QIcon()
    for size in SIZES:
        for dpr in DEVICE_PIXEL_RATIOS:
            pixmap = _render("symbolic", int(size * dpr), dpr, glyph, halo)
            if pixmap is not None:
                icon.addPixmap(pixmap)
    return icon


def tray_colors(palette: QPalette) -> tuple[QColor, QColor]:
    """Pick a legible ``(glyph, halo)`` pair for the current palette."""
    window = palette.color(QPalette.ColorRole.Window)
    window_text = palette.color(QPalette.ColorRole.WindowText)
    if _contrast(window, window_text) >= 3.0:
        return window_text, _opposite(window_text)
    if window.lightness() > 127:
        return QColor("#1c1c1c"), QColor("#ffffff")
    return QColor("#f2f2f2"), QColor("#1c1c1c")


def tray_icon(app: QApplication | None = None) -> QIcon:
    """Symbolic tray icon for ``app`` (or the active application)."""
    resolved = app if app is not None else QApplication.instance()
    if resolved is None:
        return QIcon()
    return symbolic_icon(*tray_colors(resolved.palette()))


def configure_app_icon(app: QApplication) -> None:
    """Install the full-colour icon as the application window icon."""
    app.setWindowIcon(color_icon())
```

Contract notes:

- **Import style is load-bearing.** The module must use
  `from ai_manager.resources import assets` and call `assets.asset_bytes(...)`
  at call time. Do **not** write
  `from ai_manager.resources.assets import asset_bytes`: the missing/malformed
  tests monkeypatch `ai_manager.resources.assets.asset_bytes`, and a direct-name
  binding would make them pass vacuously against the real packaged asset.
- **WCAG tint guard.** `_contrast` is the WCAG 2.x contrast ratio. Each sRGB
  channel `c` in `0..255` is linearised as `c/255 <= 0.03928 ? (c/255)/12.92 :
  (((c/255)+0.055)/1.055)**2.4`; relative luminance is
  `0.2126*R + 0.7152*G + 0.0722*B`; the ratio is
  `(L_lighter + 0.05) / (L_darker + 0.05)`. The guard threshold is `>= 3.0`.
- **Physical pixels.** `_render`'s `px` argument is the physical QImage
  dimension. `color_icon`/`symbolic_icon` therefore pass `int(size * dpr)` so
  that a `(22, dpr=2.0)` entry is a real 44x44 render carrying
  `devicePixelRatio == 2.0`.
- **No application, no `QPixmap`.** `_render` allocates and paints a `QImage`,
  then returns `None` when `QGuiApplication.instance() is None`, before
  `QPixmap.fromImage` is ever reached. Constructing a `QPixmap` without a
  `QGuiApplication` aborts the process (exit 134), so this ordering is a hard
  requirement.
- **The only deliberate raise** in this module is `ValueError` when a symbolic
  render omits either colour. Unknown kinds raise in `assets`.

---

## 6. Integration Edits

### 6.1 `src/ai_manager/main.py`

Add the import (place it with the other project imports):

Before:

```python
from ai_manager.ui.main_window import MainWindow
from ai_manager.utils.path_locator import find_ai_workspace_root
```

After:

```python
from ai_manager.ui.icons import configure_app_icon
from ai_manager.ui.main_window import MainWindow
from ai_manager.utils.path_locator import find_ai_workspace_root
```

Call the helper immediately after the `QApplication` is constructed:

Before:

```python
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName("ai-manager")
```

After:

```python
    app = QApplication(sys.argv)
    configure_app_icon(app)
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName("ai-manager")
```

`app.setDesktopFileName("ai-manager")` is unchanged; window/launcher grouping on
KDE X11 continues to rely on the `_KDE_NET_WM_DESKTOP_FILE` property, not on
`StartupWMClass`.

### 6.2 `src/ai_manager/ui/system_tray.py`

Import the tray builder and `QPalette`:

Before:

```python
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QMenu,
    QStyle,
    QSystemTrayIcon,
    QWidget,
)
```

After:

```python
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
```

Connect `paletteChanged` at the end of `__init__`:

Before:

```python
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._tray_icon = QSystemTrayIcon(parent)
        self._context_menu = QMenu(parent)
        self._init_ui()
```

After:

```python
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._tray_icon = QSystemTrayIcon(parent)
        self._context_menu = QMenu(parent)
        self._init_ui()
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._on_palette_changed)
```

Replace `_apply_icon` and add the slot:

Before:

```python
    def _apply_icon(self) -> None:
        """Best-effort icon resolution with a standard fallback."""
        app = QApplication.instance()
        if app is None:
            return
        icon = app.windowIcon()
        if icon.isNull():
            icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self._tray_icon.setIcon(icon)
```

After:

```python
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
```

Notes:

- The optional `palette` parameter matches the `paletteChanged` signal signature
  while keeping the slot callable with zero arguments from tests.
- The connection is never explicitly disconnected: the manager is parented to
  `MainWindow`, which lives for the application lifetime, and Qt destroys the
  connection with the objects.
- `app.windowIcon()` is no longer consulted by the tray.

### 6.3 `src/ai_manager/services/desktop_integration.py`

Add the Qt-free import:

Before:

```python
from ai_manager.utils.path_locator import find_ai_workspace_root
```

After:

```python
from ai_manager.resources import assets
from ai_manager.utils.path_locator import find_ai_workspace_root
```

Compute the icon value and use it:

Before:

```python
    def generate_desktop_entry(self, start_minimized: bool = False) -> str:
        """Returns FreeDesktop compliant .desktop file content."""
        lines = [
            "[Desktop Entry]",
```

After:

```python
    def generate_desktop_entry(self, start_minimized: bool = False) -> str:
        """Returns FreeDesktop compliant .desktop file content."""
        icon_path = assets.asset_path("color")
        icon_value = str(icon_path) if icon_path is not None else "applications-development"
        lines = [
            "[Desktop Entry]",
```

Before:

```python
            "Icon=utilities-system-monitor",
```

After:

```python
            f"Icon={icon_value}",
```

This module gains no Qt or `ai_manager.ui` dependency; it imports only
`ai_manager.resources.assets`.

---

## 7. Test Specifications

The interpreter for GUI/test runs is `/home/henry/anaconda3/envs/daily/bin/python`.
`tests/conftest.py` sets `QT_QPA_PLATFORM=offscreen` before pytest-qt creates
the application; do not override it in the new tests.

### 7.1 `tests/test_icons.py` (new file)

Create the file with exactly this content:

```python
"""Unit tests for the application icon pipeline (colour, symbolic, tray).

Headless via ``QT_QPA_PLATFORM=offscreen`` in ``conftest.py``; the pytest-qt
``qapp`` fixture supplies the ``QGuiApplication`` that ``QPixmap`` requires.
The no-application test deliberately runs in a subprocess with no application.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QByteArray, QSize
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPalette, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QStyle

from ai_manager.resources import assets
from ai_manager.ui import icons, system_tray
from ai_manager.ui.system_tray import SystemTrayManager

REPO_ROOT = Path(__file__).resolve().parents[1]


def _rgba_image(pixmap: QPixmap) -> QImage:
    return pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)


def _composite(pixmap: QPixmap, background: QColor) -> QImage:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    out = QImage(image.width(), image.height(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(background)
    painter = QPainter(out)
    painter.drawImage(0, 0, image)
    painter.end()
    return out.convertToFormat(QImage.Format.Format_RGBA8888)


def _palette(window: str, window_text: str) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(window))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(window_text))
    return palette


def test_assets_exist_and_parse():
    color_bytes = assets.asset_bytes("color")
    symbolic_bytes = assets.asset_bytes("symbolic")
    assert color_bytes is not None
    assert symbolic_bytes is not None
    assert QSvgRenderer(QByteArray(color_bytes)).isValid()

    substituted = symbolic_bytes.replace(b"__HALO__", b"#ffffff").replace(
        b"__GLYPH__", b"#000000"
    )
    assert b"__HALO__" not in substituted
    assert b"__GLYPH__" not in substituted
    assert QSvgRenderer(QByteArray(substituted)).isValid()


def test_color_icon_is_populated(qapp):
    icon = icons.color_icon()
    assert not icon.isNull()
    assert not icon.pixmap(QSize(22, 22)).isNull()
    available = {size.width() for size in icon.availableSizes()}
    assert {16, 22, 256} <= available


def test_symbolic_tint_is_falsifiable(qapp):
    icon = icons.symbolic_icon(QColor("#dd2222"), QColor("#22dd22"))
    image = _rgba_image(icon.pixmap(QSize(22, 22)))
    width, height = image.width(), image.height()
    total = width * height

    assert image.pixelColor(0, 0).alpha() == 0

    opaque = 0
    pure_glyph = 0
    red_over_150 = 0
    off_segment = 0
    for y in range(height):
        for x in range(width):
            color = image.pixelColor(x, y)
            if color.alpha() != 255:
                continue
            opaque += 1
            red, green, blue = color.red(), color.green(), color.blue()
            if (red, green, blue) == (221, 34, 34):
                pure_glyph += 1
            if red > 150:
                red_over_150 += 1
            if abs(blue - 34) > 3 or abs((red + green) - 255) > 3:
                off_segment += 1

    assert 0.10 * total <= opaque <= 0.60 * total
    assert red_over_150 > 0
    assert pure_glyph > 0
    assert off_segment == 0


def test_symbolic_halo_contrast(qapp):
    panel = QColor("#1c1c1c")
    icon = icons.symbolic_icon(QColor("#1c1c1c"), QColor("#ffffff"))
    image = _composite(icon.pixmap(QSize(22, 22)), panel)
    best = max(
        icons._contrast(image.pixelColor(x, y), panel)
        for y in range(image.height())
        for x in range(image.width())
    )
    assert best > 4.5


def test_tray_colors_light_palette():
    glyph, halo = icons.tray_colors(_palette("#ffffff", "#1e293b"))
    assert glyph.lightness() < 128
    assert halo.lightness() > 127


def test_tray_colors_dark_palette():
    glyph, halo = icons.tray_colors(_palette("#18181f", "#e2e8f0"))
    assert glyph.lightness() > 127
    assert halo.lightness() < 128


def test_tray_colors_low_contrast_guard():
    glyph, halo = icons.tray_colors(_palette("#f0f0f0", "#f0f0f0"))
    assert [glyph.name(), halo.name()] == ["#1c1c1c", "#ffffff"]
    assert icons._contrast(glyph, halo) > 4.5

    glyph, halo = icons.tray_colors(_palette("#101010", "#101010"))
    assert [glyph.name(), halo.name()] == ["#f2f2f2", "#1c1c1c"]
    assert icons._contrast(glyph, halo) > 4.5


def test_asset_path_returns_existing_files_and_rejects_unknown_kind():
    for kind in ("color", "symbolic"):
        path = assets.asset_path(kind)
        assert path is not None
        assert path.is_file()
    with pytest.raises(ValueError):
        assets.asset_path("bogus")


def test_missing_asset_yields_null_icon(qapp, monkeypatch):
    monkeypatch.setattr(assets, "asset_bytes", lambda kind: None)
    assert icons.color_icon().isNull()
    assert icons.symbolic_icon(QColor("#000000"), QColor("#ffffff")).isNull()


def test_malformed_asset_yields_null_icon(qapp, monkeypatch):
    monkeypatch.setattr(assets, "asset_bytes", lambda kind: b"<svg")
    assert icons.color_icon().isNull()
    assert icons.symbolic_icon(QColor("#000000"), QColor("#ffffff")).isNull()


def test_no_application_returns_null_without_abort():
    code = (
        "from ai_manager.ui import icons;"
        "c = icons.color_icon();"
        "t = icons.tray_icon(None);"
        "raise SystemExit(0 if (c.isNull() and t.isNull()) else 1)"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run([sys.executable, "-c", code], env=env)
    assert result.returncode == 0


def test_device_pixel_ratio_rendering(qapp):
    icon = icons.color_icon()
    available = {size.width() for size in icon.availableSizes()}
    assert 44 in available  # 22 logical x ratio 2.0 rendered at 44 physical px

    hidpi = icon.pixmap(QSize(22, 22), 2.0)
    assert hidpi.devicePixelRatio() == 2.0
    assert hidpi.width() == 44

    lodpi = icon.pixmap(QSize(22, 22), 1.0)
    assert lodpi.width() == 22


def test_on_palette_changed_slot_arity(qapp, monkeypatch):
    manager = SystemTrayManager()
    calls = []
    monkeypatch.setattr(
        system_tray, "tray_icon", lambda app=None: calls.append(app) or QIcon()
    )

    manager._on_palette_changed()
    manager._on_palette_changed(QPalette())

    assert len(calls) == 2


def test_standard_icon_fallback_when_tray_icon_null(qapp, monkeypatch):
    manager = SystemTrayManager()
    monkeypatch.setattr(system_tray, "tray_icon", lambda app=None: QIcon())

    manager._apply_icon()

    expected = qapp.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    assert not expected.isNull()
    assert not manager._tray_icon.icon().isNull()


def test_configure_app_icon_sets_window_icon(qapp):
    qapp.setWindowIcon(QIcon())
    icons.configure_app_icon(qapp)
    assert not qapp.windowIcon().isNull()


def test_main_calls_configure_app_icon(monkeypatch):
    import ai_manager.main as main_module

    calls = []
    monkeypatch.setattr(
        main_module, "configure_app_icon", lambda app: calls.append(app)
    )
    monkeypatch.setattr(main_module, "parse_arguments", lambda argv=None: False)
    monkeypatch.setattr(main_module, "find_ai_workspace_root", lambda: None)

    class FakeApp:
        def __init__(self, argv):
            pass

        def setQuitOnLastWindowClosed(self, value):
            pass

        def setDesktopFileName(self, value):
            pass

        def exec(self):
            return 0

    class FakeWindow:
        def __init__(self, **kwargs):
            self.is_minimized_at_startup = False

        def show(self):
            pass

    monkeypatch.setattr(main_module, "QApplication", FakeApp)
    monkeypatch.setattr(main_module, "MainWindow", FakeWindow)

    with pytest.raises(SystemExit):
        main_module.main()
    assert len(calls) == 1


def test_symbolic_render_requires_both_colours(qapp):
    with pytest.raises(ValueError):
        icons._render("symbolic", 22, 1.0, None, QColor("#ffffff"))
    with pytest.raises(ValueError):
        icons._render("symbolic", 22, 1.0, QColor("#000000"), None)
```

### 7.2 `tests/test_desktop_integration.py` (modified)

Add the assets import:

Before:

```python
from ai_manager.services import desktop_integration
from ai_manager.services.desktop_integration import DesktopIntegrationService
```

After:

```python
from ai_manager.resources import assets
from ai_manager.services import desktop_integration
from ai_manager.services.desktop_integration import DesktopIntegrationService
```

Replace the stale assertion on the current line 86 (its current text is exactly
`    assert "Icon=utilities-system-monitor" in content`):

Before:

```python
    assert f"Path={tmp_path}" in content
    assert "Icon=utilities-system-monitor" in content
    assert "Terminal=false" in content
```

After:

```python
    assert f"Path={tmp_path}" in content
    icon_line = next(
        line for line in content.splitlines() if line.startswith("Icon=")
    )
    icon_path = assets.asset_path("color")
    assert icon_path is not None
    assert icon_line == f"Icon={icon_path}"
    assert icon_path.is_file()
    assert "Terminal=false" in content
```

Add the fallback test directly after `test_generate_desktop_entry_minimized_flag`:

```python
def test_generate_desktop_entry_falls_back_when_asset_missing(tmp_path, monkeypatch):
    service = DesktopIntegrationService(workspace_root=tmp_path)
    monkeypatch.setattr(desktop_integration.assets, "asset_path", lambda kind: None)

    content = service.generate_desktop_entry()

    assert "Icon=applications-development" in content
```

### 7.3 `tests/test_system_tray.py` (modified)

Add imports:

Before:

```python
import pytest
from PyQt6.QtWidgets import QSystemTrayIcon

from ai_manager.ui.system_tray import SystemTrayManager
```

After:

```python
import pytest
from PyQt6.QtGui import QIcon, QPalette
from PyQt6.QtWidgets import QSystemTrayIcon

from ai_manager.ui import system_tray
from ai_manager.ui.system_tray import SystemTrayManager
```

Append these two tests at the end of the file:

```python
def test_tray_icon_is_not_null_after_construction(manager):
    assert manager._tray_icon.icon().isNull() is False


def test_palette_changed_reapplies_icon(qapp, monkeypatch, manager):
    calls = []
    monkeypatch.setattr(
        system_tray, "tray_icon", lambda app=None: calls.append(app) or QIcon()
    )

    qapp.paletteChanged.emit(qapp.palette())

    assert len(calls) == 1
```

---

## 8. Packaging (`pyproject.toml`)

Append exactly this block to `pyproject.toml` (there is currently no
`[tool.setuptools.*]` section, so add it at end of file):

```toml
[tool.setuptools.package-data]
ai_manager = ["resources/icons/*.svg"]
```

---

## 9. Interface Contracts

| Name | Signature | Inputs | Outputs | Failure mode |
|---|---|---|---|---|
| `assets._TABLE` | `dict[str, str]` | — | `{"color": "ai-manager.svg", "symbolic": "ai-manager-symbolic.svg"}` | — |
| `assets._filename` | `(kind: str) -> str` | validated kind string | mapped filename | `ValueError` for unknown `kind`; never returns `None`. |
| `assets._traversable` | `(kind: str) -> Traversable` | kind string | `Traversable` into `ai_manager/resources/icons/` | `ValueError` (unknown kind), `ModuleNotFoundError` (package absent) propagate; no swallowing here. |
| `assets.asset_bytes` | `(kind: str) -> bytes \| None` | kind string | raw bytes | `ValueError` for unknown kind (hard); `None` for missing package/file (`ModuleNotFoundError`/`OSError`). |
| `assets.asset_path` | `(kind: str) -> Path \| None` | kind string | existing `Path` | `ValueError` for unknown kind (hard); `None` if package/file unavailable or path not a file. |
| `icons.SIZES` | `tuple[int, ...]` | — | `(16, 22, 24, 32, 48, 64, 128, 256)` | — |
| `icons.DEVICE_PIXEL_RATIOS` | `tuple[float, ...]` | — | `(1.0, 2.0)` | — |
| `icons._channel_luminance` | `(component: int) -> float` | sRGB component `0..255` | linearised `0..1` | none. |
| `icons._relative_luminance` | `(color: QColor) -> float` | colour | WCAG relative luminance | none. |
| `icons._contrast` | `(a: QColor, b: QColor) -> float` | two colours | WCAG ratio `1.0..21.0` | none. |
| `icons._opposite` | `(glyph: QColor) -> QColor` | colour | `#ffffff` if `lightness() < 128` else `#1c1c1c` | none. |
| `icons._render` | `(kind: str, px: int, device_pixel_ratio: float, glyph: QColor \| None, halo: QColor \| None) -> QPixmap \| None` | physical `px`; colours required only for `"symbolic"` | `QPixmap` with `devicePixelRatio` set | `None` for missing bytes or invalid SVG; `None` (before any `QPixmap`) when no `QGuiApplication`; `ValueError` for symbolic with a missing colour. Never aborts. |
| `icons.color_icon` | `() -> QIcon` | — | populated `QIcon`, or null | never raises; null `QIcon` on any render failure or no application. |
| `icons.symbolic_icon` | `(glyph: QColor, halo: QColor) -> QIcon` | two colours | populated `QIcon`, or null | never raises; null on failure/no application. |
| `icons.tray_colors` | `(palette: QPalette) -> tuple[QColor, QColor]` | palette | `(glyph, halo)` | never raises. |
| `icons.tray_icon` | `(app: QApplication \| None = None) -> QIcon` | optional app; falls back to `QApplication.instance()` | symbolic `QIcon`, or null | never raises; null `QIcon` when no application. |
| `icons.configure_app_icon` | `(app: QApplication) -> None` | application | none; calls `app.setWindowIcon(color_icon())` | never raises (may set a null icon). |
| `SystemTrayManager._apply_icon` | `(self) -> None` | — | tray icon set to `tray_icon(app)` or `SP_ComputerIcon` fallback | returns early when no `QApplication`. |
| `SystemTrayManager._on_palette_changed` | `(self, palette: QPalette \| None = None) -> None` | optional palette (signal payload) | calls `_apply_icon()` | never raises; safe with zero or one argument. |
| `DesktopIntegrationService.generate_desktop_entry` | `(self, start_minimized: bool = False) -> str` | optional flag | `.desktop` text with `Icon=<colour asset path>` or `Icon=applications-development` | never raises for a missing asset (`asset_path` returns `None`). |

---

## 10. Test Matrix

Legend: **T** = `tests/test_icons.py`, **S** = `tests/test_system_tray.py`,
**D** = `tests/test_desktop_integration.py`. Design item numbers refer to
`docs/superpowers/specs/2026-10-04-app-icon-design.md` section 7.

| ID | Test | Pins | Falsifiability (how it fails if the mechanism breaks) |
|---|---|---|---|
| T1 | `test_assets_exist_and_parse` (design 1) | Both assets resolve to bytes, and both the colour SVG and the substituted symbolic SVG are valid `QSvgRenderer` documents. | Delete/misplace either SVG, or misspell a token so it is not substituted and remains invalid markup → `asset_bytes` returns `None` or `isValid()` is `False` → assertion fails. |
| T2 | `test_color_icon_is_populated` (design 2) | `color_icon()` is non-null, `pixmap(QSize(22,22))` is non-null, `availableSizes()` contains 16, 22, 256. | Make `_render` always return `None`, or shrink `SIZES` → `isNull()`/missing size → assertion fails. |
| T3 | `test_symbolic_tint_is_falsifiable` (design 3) | Corner transparent; fully opaque pixels are 10–60% of the canvas; at least one opaque pixel has `red > 150`; every opaque pixel satisfies `abs(blue-34) <= 3` and `abs(red+green-255) <= 3`. Reference render: 76/484 opaque (15.7%), 34 pure glyph, 0 off-segment. | Verified by mutation: forcing the tokens to `#000000` gives `off_segment > 0` and `red_over_150 == 0` → fails. Dropping substitution leaves invalid tokens → null render → `red_over_150 == 0` → fails. A `SourceOver` full-canvas fill exceeds the 60% cap. |
| T4 | `test_symbolic_halo_contrast` (design 4) | With glyph `#1c1c1c`/halo `#ffffff` composited on a `#1c1c1c` panel, some pixel exceeds WCAG contrast 4.5. | Verified by mutation: the without-halo control render measures best contrast 1.23 → the same assertion fails. Removing the halo layer from the asset therefore fails the test. |
| T5 | `test_tray_colors_light_palette` (design 5) | Light palette (`#ffffff`/`#1e293b`) → dark glyph, light halo. | Invert/replace the branch → lightness ordering assertion fails. |
| T6 | `test_tray_colors_dark_palette` (design 5) | Dark palette (`#18181f`/`#e2e8f0`) → light glyph, dark halo. | As T5. |
| T7 | `test_tray_colors_low_contrast_guard` (design 5) | Identical `Window`/`WindowText` (contrast 1.0) light → exactly `#1c1c1c`/`#ffffff`; dark → exactly `#f2f2f2`/`#1c1c1c`; each pair contrast > 4.5. | Remove the `>= 3.0` guard so `WindowText` is returned directly: for `#f0f0f0` the glyph becomes `#f0f0f0` instead of `#1c1c1c` → exact-value assertion fails. |
| T8 | `test_asset_path_returns_existing_files_and_rejects_unknown_kind` (design 6) | `asset_path("color")`/`("symbolic")` exist; `asset_path("bogus")` raises `ValueError`. | Make unknown kinds default to `"color"` → `pytest.raises(ValueError)` fails; break the data directory → `is_file()` fails. |
| T9 | `test_missing_asset_yields_null_icon` (design 7) | With `assets.asset_bytes` monkeypatched to `None`, both builders return null icons without raising. | Verified by mutation: changing `icons.py` to `from ai_manager.resources.assets import asset_bytes` and calling `asset_bytes(kind)` makes the monkeypatch vacuous → real asset loads → `isNull()` is `False` → fails. |
| T10 | `test_malformed_asset_yields_null_icon` (design 8) | With `assets.asset_bytes` returning `b"<svg"`, both builders return null icons, not a raise. | Remove the `renderer.isValid()` guard → a non-null or crashing path → assertion/exception fails; restore a direct-name import → vacuous non-null → fails. |
| T11 | `test_no_application_returns_null_without_abort` (design 9) | A subprocess with no `QApplication` calls `color_icon()` and `tray_icon(None)` and exits 0 with both null. | Verified by mutation: moving the `QGuiApplication.instance()` check after `QPixmap.fromImage` makes the subprocess abort (exit 134) → `returncode == 0` fails. |
| T12 | `test_device_pixel_ratio_rendering` (design 10) | `availableSizes()` contains 44; `pixmap(QSize(22,22), 2.0)` has `devicePixelRatio() == 2.0` and `width() == 44`; ratio-1.0 query width 22. | Verified by mutation: passing `size` instead of `size * dpr` to `_render` removes the 44 physical entry from `availableSizes()` → `assert 44 in available` fails. |
| T13 | `test_on_palette_changed_slot_arity` (design 11) | `_on_palette_changed()` and `_on_palette_changed(QPalette())` each trigger one `tray_icon` call. | Change the slot to require a positional argument → `TypeError`; stop calling `_apply_icon` → count 0/1 mismatch. |
| T14 | `test_standard_icon_fallback_when_tray_icon_null` (design 12) | With `system_tray.tray_icon` monkeypatched to a null icon, `_apply_icon()` installs the non-null `SP_ComputerIcon`. | With the old `app.windowIcon()` code the attribute `system_tray.tray_icon` does not exist → the monkeypatch raises `AttributeError`; if the fallback were removed, `_tray_icon.icon()` is null → fails. |
| T15 | `test_configure_app_icon_sets_window_icon` (design 13) | `configure_app_icon(qapp)` leaves `qapp.windowIcon()` non-null. | Make `configure_app_icon` a no-op → window icon stays null → fails. |
| T16 | `test_main_calls_configure_app_icon` (design 13) | `main()` invokes `configure_app_icon(app)` exactly once. | Verified by mutation: deleting `configure_app_icon(app)` from `main.py` → `calls == []` → `len(calls) == 1` fails. |
| T17 | `test_symbolic_render_requires_both_colours` (design 14) | `_render("symbolic", ...)` raises `ValueError` when either colour is `None`. | Remove the guard → `pytest.raises(ValueError)` fails. |
| S1 | `test_tray_icon_is_not_null_after_construction` (design 7 additions) | After `SystemTrayManager()`, `_tray_icon.icon().isNull()` is `False`. | Weak by construction (the old `SP_ComputerIcon` fallback is also non-null); it still fails if `_apply_icon` stops calling `setIcon` entirely. The substantive pin is S2. |
| S2 | `test_palette_changed_reapplies_icon` (design 7 additions) | Emitting `qapp.paletteChanged` triggers exactly one `tray_icon` call. | Verified by mutation: removing the `app.paletteChanged.connect(...)` line → count 0 → `len(calls) == 1` fails. |
| D1 | `test_generate_desktop_entry_contains_required_keys` (design 7 additions, replaces line 86) | The `Icon=` line equals `f"Icon={assets.asset_path('color')}"` and that path is a file. | If the entry keeps `Icon=utilities-system-monitor` or the wrong path → string mismatch and/or `is_file()` fails. |
| D2 | `test_generate_desktop_entry_falls_back_when_asset_missing` (design 7 additions) | With `asset_path` monkeypatched to `None`, `Icon=applications-development` is present. | Removing the `is not None` fallback (e.g. `f"Icon={asset_path('color')}"` rendering `Icon=None`) → assertion fails. |

---

## 11. Environment and Commands

| Item | Value |
|---|---|
| Project interpreter (GUI + tests) | `/home/henry/anaconda3/envs/daily/bin/python` (Python 3.14.6, PyQt6 6.11.0 / Qt 6.11.0) |
| Headless platform | `QT_QPA_PLATFORM=offscreen` — already set by `tests/conftest.py`; do not set or override it in tests. |
| Full suite | `PYTHONPATH=src pytest tests/` |
| New tests only | `PYTHONPATH=src pytest tests/test_icons.py` |
| Changed tests only | `PYTHONPATH=src pytest tests/test_desktop_integration.py tests/test_system_tray.py` |
| Focused run example | `PYTHONPATH=src pytest tests/test_icons.py::test_symbolic_tint_is_falsifiable -q` |
| Manual render check | `/home/henry/anaconda3/envs/daily/bin/python docs/superpowers/specs/mockups/generate_icon_preview.py` (writes `app_icon_preview.png`) |

If `pytest` is not on `PATH`, invoke it as
`/home/henry/anaconda3/envs/daily/bin/python -m pytest ...` with the same
`PYTHONPATH=src`. The subprocess test in `test_icons.py` re-derives the source
path from `Path(__file__).resolve().parents[1] / "src"`, so it does not depend on
the caller's `PYTHONPATH`.

---

## 12. Verification Checklist

Run before claiming completion. Each item must be observed, not assumed.

1. `src/ai_manager/resources/__init__.py` exists and is 0 bytes.
2. Both SVGs exist; `wc -c` reports exactly 492 and 870 bytes; neither has a
   trailing newline; the symbolic file still contains both `__GLYPH__` and
   `__HALO__` and no `#rrggbb` value.
3. `PYTHONPATH=src pytest tests/test_icons.py` passes.
4. `PYTHONPATH=src pytest tests/test_desktop_integration.py tests/test_system_tray.py`
   passes (the stale `utilities-system-monitor` assertion is gone).
5. `PYTHONPATH=src pytest tests/` passes in full with no new failures.
6. `grep -n "Icon=" src/ai_manager/services/desktop_integration.py` shows the
   computed `f"Icon={icon_value}"` form, not a literal theme name.
7. `grep -n "from ai_manager.resources.assets import" src/ai_manager/ui/icons.py`
   finds nothing (module-qualified access is required).
8. `grep -n "configure_app_icon" src/ai_manager/main.py` finds both the import
   and the call after `QApplication(sys.argv)`.
9. `grep -n "paletteChanged" src/ai_manager/ui/system_tray.py` finds the
   connection in `__init__`.
10. Mutation spot-checks (optional but recommended; each must fail then pass
    after revert):
    - Force both symbolic tokens to `#000000` → `test_symbolic_tint_is_falsifiable`
      fails.
    - Pass `size` instead of `int(size * dpr)` to `_render` in `color_icon` →
      `test_device_pixel_ratio_rendering` fails.
    - Move the `QGuiApplication.instance()` check after `QPixmap.fromImage` →
      `test_no_application_returns_null_without_abort` fails.
    - Remove the `paletteChanged` connection → `test_palette_changed_reapplies_icon`
      fails.
    - Remove `configure_app_icon(app)` from `main.py` →
      `test_main_calls_configure_app_icon` fails.
11. `python -c "import ai_manager.resources.assets"` does not import Qt (no Qt
    import in that module).

---

## 13. Interpretations and Contradictions Resolved

Every item below is resolved in favour of the design document.

1. **`_render` physical-pixel argument (design §3.2).** The design shows the
   call as `_render("color", size, dpr, None, None)` but then says it is
   "rendered at `size * dpr` physical pixels", and `_render` step 4 allocates
   `QImage(px, px, ...)`. To satisfy both, `px` is interpreted as the physical
   pixel count and the builders pass `int(size * dpr)`. If `px` were the logical
   size, no 44x44 entry would exist and the design's own device-pixel-ratio
   expectation (`width() == 44`) would rely on Qt upscaling.
2. **Device-pixel-ratio test strengthening (design §7 item 10).** The literal
   assertions (`devicePixelRatio() == 2.0`, `width() == 44`, ratio-1.0 width 22)
   also pass when `_render` receives the logical size, because Qt upscales on
   `pixmap()` extraction. One assertion was added — `44 in availableSizes()` —
   so the test actually pins the documented "size * dpr physical pixels"
   behaviour. This adds no feature; it pins a design statement.
3. **`desktop_integration` import style (design §4.3, §7).** The design says the
   module "imports only `ai_manager.resources.assets`" and separately that a test
   "monkeypatches `asset_path`". It is implemented as
   `from ai_manager.resources import assets` with `assets.asset_path("color")`
   at call time, matching the module-object convention of `ui/icons.py` and
   keeping the monkeypatch effective. The fallback test patches
   `desktop_integration.assets.asset_path` (the same module object).
4. **`assets.py` internals (design §3.1).** The design gives only the two
   signatures; the implementation adds `_filename` and a `Traversable`-typed
   `_traversable` helper and resolves through
   `importlib.resources.files("ai_manager.resources").joinpath("icons", name)`.
   This is data-directory access, so `resources/icons/__init__.py` must **not**
   be added.
5. **`asset_path` existence check (design §3.1).** "or `None` when unavailable"
   is interpreted to include a resolved path that does not exist on disk
   (`is_file()` check), so the `.desktop` fallback triggers for a missing file
   as well as a missing package.
6. **`_contrast` is private but used by tests (design §7 items 4/5).** The WCAG
   helper is not part of the public API listed in §3.2. Tests call
   `icons._contrast(...)`; this is accepted because tests live in the same
   package and no public helper is specified.
7. **`test_tray_icon_is_not_null_after_construction` is weak (design §7
   additions).** The assertion is non-null, which the pre-existing
   `SP_ComputerIcon` fallback also satisfied. It is retained verbatim as
   required; the meaningful re-tint contract is covered by
   `test_palette_changed_reapplies_icon`.
8. **Empty `__init__.py` (design §3.3).** No docstring or imports are added so
   the "empty" statement remains literally true.
