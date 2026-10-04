# Design Document: Application Icon Set (Tray, Window, Launcher)

## 1. Background & Goals

`ai-manager` ships no icon assets. `SystemTrayManager._apply_icon()` reads
`QApplication.windowIcon()`, which is never set, so it always falls back to
`QStyle.StandardPixmap.SP_ComputerIcon` — a beige CRT monitor. The window
titlebar/taskbar likewise has no icon, and the installed `.desktop` entry uses
`Icon=utilities-system-monitor`, a generic system-monitor glyph.

Goal: give the application a distinctive, purpose-drawn icon that reads clearly
at KDE system-tray size (22px), plus a full-colour variant for the window and
launcher.

Target environment (verified): KDE Plasma 6 on X11, KDE colour scheme
`Breeze Light` (light panel), Plasma theme `WhiteSur-alt`, Qt 6.11.2 under
`PyQt6` 6.11.0. The runtime interpreter is the conda env `daily` (activated by
`start.sh`).

### 1.1 Constraints discovered

- The system interpreter's `PyQt6` (`/usr/lib/python3.14/site-packages/PyQt6`)
  has **no** `Qt6/plugins/iconengines/` directory, so `QIcon("*.svg")` silently
  produces nothing there. The conda `daily` env and `/usr/lib/qt6` do ship
  `libqsvgicon.so`. The design must not depend on the SVG icon-engine plugin.
- `QIcon.fromTheme()` + Plasma's own symbolic recolouring requires a theme-cache
  refresh and Qt sending `IconName` over StatusNotifierItem. That chain is
  fragile and is deliberately not used.
- `QSvgRenderer` renders correctly under `QT_QPA_PLATFORM=offscreen` without a
  display, which makes the icon pipeline unit-testable.

## 2. Visual Design

Motif: an **orchestration hub** — one central node linked to three satellites,
mapping to the three supervised services (`ai-grammar`, `textkit`, `yt2txt`).
Chosen over a chip, stacked slabs and a gauge for legibility at 22px.

### 2.1 Canonical geometry

24×24 viewBox, hub centre at `(12, 13.5)`, satellites at angles 90°/210°/330°
at radius `7.1` from the hub:

| Element        | Geometry                                              |
|----------------|-------------------------------------------------------|
| Hub            | circle `(12, 13.5)` r `3.5`                           |
| Satellites (3) | circles `(12, 6.4)`, `(5.85, 17.05)`, `(18.15, 17.05)` r `2.0` |
| Links (3)      | lines from hub centre to each satellite, stroke `1.5`, `stroke-linecap="round"` |

The hub is deliberately offset downward by `1.5` so the *bounding box*
(`y 4.4 … 19.05`) is optically centred in the square canvas. All geometry stays
within a 2px margin, so nothing clips at any render size.

Verified raster output at 16/22/32/48/64/128px on both a light (`#f0f0f0`) and a
dark (`#18181f`) background; the hub dominates and the satellites read as
endpoints. Reproduce with
`docs/superpowers/specs/mockups/generate_icon_preview.py`, which writes
`docs/superpowers/specs/mockups/app_icon_preview.png` (side-by-side with the
current `SP_ComputerIcon` fallback). Rejected variants (recorded for future
reference): gap-separated spokes (looks broken at 22px), point-down triangle
(reads as a falling "Y"), four satellites with or without links (loses the
"three managed services" meaning).

### 2.2 Exact assets

`src/ai_manager/resources/icons/ai-manager.svg`:

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

`src/ai_manager/resources/icons/ai-manager-symbolic.svg` is byte-identical
except every `#3B82F6` and `#60A5FA` is replaced with `#000000`. It is used as
an **alpha mask only**: its colour is discarded and replaced by a runtime tint.

Colour roles: hub and links `#3B82F6` (the application's existing primary
accent), satellites `#60A5FA` (lighter tint of the same hue). No gradients —
they band at small sizes and would not match the flat QSS theme.

## 3. Architecture & Components

One new module with one responsibility: convert packaged SVG resources into
correctly sized, correctly tinted `QIcon` objects.

### 3.1 `src/ai_manager/ui/icons.py`

```python
SIZES: tuple[int, ...] = (16, 22, 24, 32, 48, 64, 128, 256)

def color_icon() -> QIcon: ...                      # two-tone, multi-size
def symbolic_icon(tint: QColor) -> QIcon: ...       # mask recoloured to tint
def tray_tint(palette: QPalette) -> QColor: ...     # foreground for the tray
def tray_icon(app: QApplication | None = None) -> QIcon: ...
def icon_path(kind: str = "color") -> Path: ...     # for the .desktop entry
```

- `_asset_bytes(name: str) -> bytes | None` reads
  `importlib.resources.files("ai_manager.resources").joinpath(f"icons/{name}").read_bytes()`
  and returns `None` on any `OSError`/`ModuleNotFoundError`.
- `_render(name: str, px: int, tint: QColor | None) -> QPixmap | None`:
  1. `QSvgRenderer(QByteArray(data))`; return `None` if `not renderer.isValid()`.
  2. Allocate `QImage(px, px, Format_ARGB32_Premultiplied)`, fill transparent,
     `QPainter` with `RenderHint.Antialiasing`, `renderer.render(painter)`.
  3. If `tint` is not `None`, repaint the *same* image with
     `CompositionMode_SourceIn` and `fillRect(image.rect(), tint)`. (Painting the
     tint as source over the icon as destination is the correct direction;
     drawing the icon onto a tint-filled image is a no-op and is the bug that
     produced a black "light" icon during design.)
  4. Return `QPixmap.fromImage(image)`.
- `color_icon()` / `symbolic_icon(tint)` build a `QIcon` and `addPixmap` one
  render per entry in `SIZES`. A `QIcon` with no successfully rendered pixmap is
  returned as a null `QIcon` rather than raising.
- `tray_tint(palette)` returns `palette.color(QPalette.ColorRole.WindowText)`,
  subject to a contrast guard: compute the WCAG relative-luminance contrast
  ratio between `palette.color(Window)` and that foreground; if it is below
  `3.0`, return `QColor("#1c1c1c")` when `Window.lightness() > 127`, else
  `QColor("#f2f2f2")`. Under Breeze Light this yields a dark glyph on the light
  panel.
- `tray_icon(app=None)` resolves `app = app or QApplication.instance()`; if that
  is still `None` it uses the fallback tint `QColor("#f2f2f2")` directly, then
  returns `symbolic_icon(tray_tint(resolved.palette()))` when an application
  exists.
- `icon_path(kind)` returns
  `Path(importlib.resources.files("ai_manager.resources").joinpath("icons", filename))`,
  where `filename` maps `"color"` (default) → `ai-manager.svg` and
  `"symbolic"` → `ai-manager-symbolic.svg`. It is used to fill the `.desktop`
  `Icon=` field, so it assumes a non-zipped (directory or editable) install;
  zipped installs are out of scope, because the generated `.desktop` entry
  already requires a real on-disk checkout for `Exec=`/`Path=`.

### 3.2 Packaging

`src/ai_manager/resources/__init__.py` (empty) makes `resources` a real
subpackage so `importlib.resources` works from both a source checkout
(`PYTHONPATH=src`) and an installed wheel. `pyproject.toml` gains:

```toml
[tool.setuptools.package-data]
ai_manager = ["resources/icons/*.svg"]
```

## 4. Integration

### 4.1 `src/ai_manager/main.py`

After the `QApplication` is constructed, call
`app.setWindowIcon(color_icon())`. This covers the window titlebar, the taskbar
entry, and the `StartupWMClass=ai-manager` association.

### 4.2 `src/ai_manager/ui/system_tray.py`

Replace the body of `_apply_icon()`:

```python
def _apply_icon(self) -> None:
    app = QApplication.instance()
    if app is None:
        return
    icon = tray_icon(app)
    if icon.isNull():
        icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    self._tray_icon.setIcon(icon)
```

`__init__` additionally connects `app.paletteChanged` (when an application
instance exists) to a new `_on_palette_changed` slot that calls `_apply_icon()`,
so a runtime KDE colour-scheme switch re-tints the icon. `app.windowIcon()` is
no longer consulted for the tray.

### 4.3 `src/ai_manager/services/desktop_integration.py`

`generate_desktop_entry()` writes `Icon={self._icon_path()}` where `_icon_path()`
returns `str(icon_path("color"))`, replacing the literal
`Icon=utilities-system-monitor`. Because the entry already stores absolute
`Exec=` and `Path=` values, an absolute icon path is consistent rather than a
new constraint.

## 5. Data Flow

```
resources/icons/*.svg
        │  importlib.resources.read_bytes()
        ▼
   QSvgRenderer ──invalid──▶ None ──▶ null QIcon ──▶ SP_ComputerIcon fallback
        │ valid
        ▼
  QImage(px, px) ──(optional) CompositionMode_SourceIn + tint──▶ QPixmap
        │  for px in SIZES
        ▼
      QIcon ──▶ QSystemTrayIcon.setIcon()   (symbolic, palette-tinted)
            ──▶ QApplication.setWindowIcon() (colour)
            ──▶ .desktop Icon= absolute path (colour)
```

## 6. Error Handling

- A missing, unreadable or malformed SVG yields a null `QIcon`; it never raises
  and never aborts startup. The tray keeps its existing `SP_ComputerIcon`
  fallback, the window simply has no icon.
- Icon construction must not require a display; `QSvgRenderer` is the only Qt
  dependency and works offscreen.
- `paletteChanged` is connected only when `QApplication.instance()` is not
  `None`.

## 7. Testing

New `tests/test_icons.py` (headless via the existing
`QT_QPA_PLATFORM=offscreen` in `conftest.py`, using the `qapp` fixture from
pytest-qt):

1. Both assets exist and `QSvgRenderer(QByteArray(bytes)).isValid()` is `True`.
2. `color_icon()` is not null; `pixmap(QSize(22, 22))` is not null;
   `availableSizes()` contains `16`, `22` and `256`.
3. `symbolic_icon(QColor("#ff0000"))` produces a pixmap with at least one
   pixel whose red channel dominates, proving the tint is applied (guards
   against the source/destination inversion bug).
4. `tray_tint()` returns a dark colour for a light `QPalette` and a light colour
   for a dark one (palettes constructed directly, not from the environment).
5. `icon_path("color").is_file()` and `icon_path("symbolic").is_file()`.
6. Missing-asset path: monkeypatch `_asset_bytes` to return `None` and assert
   `color_icon().isNull()` and `tray_icon(None).isNull()` without raising.

Additions to existing tests:

- `tests/test_system_tray.py`: after constructing `SystemTrayManager()`,
  `manager._tray_icon.icon().isNull()` is `False`.
- `tests/test_desktop_integration.py`: the generated entry contains a line
  `Icon=<absolute path>` and `Path(icon_value).is_file()` is `True`.

## 8. Out of Scope / Known Caveats

- The `.desktop` entry keeps an **absolute** icon path, so it breaks if the
  repository moves. This matches the existing absolute `Exec=`/`Path=` fields;
  installing into `hicolor` with a themed name is deliberately deferred.
- The already-installed `~/.local/share/applications/ai-manager.desktop`
  (`Icon=utilities-system-monitor`) only picks up the new icon when the shortcut
  is re-installed from the Settings dialog. The design does not rewrite
  existing user entries on startup.
- Plasma's own symbolic-icon recolouring is not used, so third-party
  monochrome-override behaviour does not apply; the tint is chosen by us from
  the Qt palette.
- No light/dark variants of the colour asset are produced; the two-tone blue is
  used unchanged for window and launcher.
