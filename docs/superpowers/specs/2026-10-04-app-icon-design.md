# Design Document: Application Icon Set (Tray, Window, Launcher)

Revision 2 — incorporates the frontier design review of revision 1.

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

### 1.1 Environment findings

- **SVG icon engines are available; they are not the reason for this design.**
  The system interpreter's `PyQt6` package has no bundled `Qt6/plugins/`
  directory, but it links the system Qt6 whose `QApplication.libraryPaths()`
  resolves to `['/usr/lib/qt6/plugins', '/usr/bin']`, and
  `/usr/lib/qt6/plugins/iconengines/libqsvgicon.so` exists. Measured under the
  system interpreter: `QIcon(<svg path>).pixmap(QSize(22, 22))` renders
  (non-null, accent pixel present). The conda `daily` env additionally bundles
  its own `libqsvgicon.so`. *An earlier revision of this document wrongly
  claimed `QIcon("*.svg")` "silently produces nothing" on the system
  interpreter; that claim is withdrawn.*
- **The real rationale for rendering with `QSvgRenderer`** is control, not
  plugin availability: it lets us rasterise an exact size, produce a
  deterministic recoloured mask (a tint, or a two-tone glyph/halo pair), and
  attach a device-pixel-ratio to each pixmap. `QIcon(path)` offers none of
  those.
- **`QSvgRenderer` implements the SVG Tiny 1.2 profile.** Gradients, filters,
  masks and clipping degrade silently. The shipped assets therefore use only
  paths, lines, circles and solid fills, and the module docstring must record
  this limit so future edits do not reach for unsupported features.
- **`QPixmap` requires a `QGuiApplication`.** `QPixmap.fromImage()` with no
  application aborts the process (`Aborted (core dumped)`, exit 134 —
  reproduced). The icon module therefore builds `QImage` internally and only
  converts to `QPixmap` when `QGuiApplication.instance()` is not `None`.
- `QIcon.fromTheme()` plus Plasma's own symbolic recolouring needs a
  theme-cache refresh and Qt sending `IconName` over StatusNotifierItem. That
  chain is not used; the icon is fully self-contained.
- `QSvgRenderer` and the whole pipeline work under
  `QT_QPA_PLATFORM=offscreen` with no display, so every claim below is
  unit-testable.

### 1.2 Tray legibility

The tray glyph is composited by `plasmashell` over the **panel**, whose
background follows the Plasma theme, not the Qt colour scheme. A single-colour
symbolic glyph tinted from the application `QPalette` is therefore not
guaranteed legible: a dark glyph on a dark panel is invisible (verified by
rendering — the glyph all but disappears).

The design resolves this without relying on any panel-query API by making the
symbolic asset **two-tone**: a glyph plus a contrasting halo drawn underneath
it. Whichever way the panel sits, either the glyph or its halo contrasts with
it. When the application palette matches the panel (the normal case, since
`KDEPlasmaPlatformTheme6.so` supplies the KDE palette) the halo blends into the
panel and the icon reads as a clean solid glyph; when they disagree it reads as
a crisp outlined glyph. Both outcomes are legible.

## 2. Visual Design

Motif: an **orchestration hub** — one central node linked to three satellites,
mapping to the three supervised services (`ai-grammar`, `textkit`, `yt2txt`).
Chosen over a chip, stacked slabs and a gauge for legibility at 22px.

### 2.1 Canonical geometry

24×24 viewBox, hub centre at `(12, 13.5)`, satellites at angles 90°/210°/330°
at radius `7.1` from the hub. Constants: `HUB=3.5`, `SAT=2.0`, `STROKE=1.5`,
`HALO=0.8`.

| Element        | Colour asset                                   | Symbolic glyph layer | Symbolic halo layer |
|----------------|------------------------------------------------|----------------------|---------------------|
| Hub            | circle `(12,13.5)` r `3.5`                     | r `3.5`              | r `4.3`             |
| Satellites (3) | `(12,6.4)`, `(5.85,17.05)`, `(18.15,17.05)` r `2.0` | r `2.0`         | r `2.8`             |
| Links (3)      | hub centre → each satellite, stroke `1.5`, round | stroke `1.5`      | stroke `3.1`        |

The hub is deliberately offset downward by `1.5` so the *bounding box*
(`y 4.4 … 19.05`) is optically centred in the square canvas. Glyph geometry stays
within a 2px margin; the halo layer reaches `y 3.6 … 19.85` and `x 3.85 … 20.15`,
still inside the 24px canvas.

Verified raster output at 16/22/32/48/64/128px on light (`#f0f0f0`) and dark
(`#18181f`) panels, with and without the halo. Reproduce with
`docs/superpowers/specs/mockups/generate_icon_preview.py`, which writes
`docs/superpowers/specs/mockups/app_icon_preview.png` (side-by-side with the
current `SP_ComputerIcon` fallback). Rejected variants (recorded for future
reference): gap-separated spokes (looks broken at 22px), point-down triangle
(reads as a falling "Y"), four satellites with or without links (loses the
"three managed services" meaning).

### 2.2 Exact assets

`src/ai_manager/resources/icons/ai-manager.svg` — full colour, no tokens:

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

`src/ai_manager/resources/icons/ai-manager-symbolic.svg` — a **two-token
template**, not a flat mask. The literal tokens `__HALO__` and `__GLYPH__` are
substituted with `#rrggbb` strings before parsing; the file is never parsed
uns substituted:

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

Colour roles: hub and links `#3B82F6` (the application's existing primary
accent), satellites `#60A5FA` (a lighter tint of the same hue). No gradients —
they band at small sizes, do not match the flat QSS theme, and fall outside the
SVG Tiny 1.2 profile that `QSvgRenderer` implements.

## 3. Architecture & Components

Two modules with one responsibility each, split so that no Qt import leaks into
a service module.

### 3.1 `src/ai_manager/resources/assets.py` (Qt-free)

Pure `importlib.resources` + `pathlib`; imports no Qt.

```python
_TABLE: dict[str, str] = {
    "color": "ai-manager.svg",
    "symbolic": "ai-manager-symbolic.svg",
}

def asset_bytes(kind: str) -> bytes | None:
    """Raw bytes of a packaged icon asset, or None when unavailable."""

def asset_path(kind: str) -> Path | None:
    """Filesystem path of a packaged icon asset, or None when unavailable."""
```

- Unknown `kind` raises `ValueError` (never silently defaults), so a typo in a
  caller is a loud failure in tests.
- Both functions swallow `ModuleNotFoundError` and `OSError` and return `None`
  when the resource package or file is unavailable, so neither raises into the
  `.desktop` generation path.
- `asset_path` assumes a non-zipped (directory or editable) install. Zipped
  installs are out of scope because the generated `.desktop` entry already
  requires a real on-disk checkout for its absolute `Exec=`/`Path=` fields.

### 3.2 `src/ai_manager/ui/icons.py`

```python
SIZES: tuple[int, ...] = (16, 22, 24, 32, 48, 64, 128, 256)
DEVICE_PIXEL_RATIOS: tuple[float, ...] = (1.0, 2.0)

def color_icon() -> QIcon: ...
def symbolic_icon(glyph: QColor, halo: QColor) -> QIcon: ...
def tray_colors(palette: QPalette) -> tuple[QColor, QColor]: ...
def tray_icon(app: QApplication | None = None) -> QIcon: ...
```

- `_render(kind, px, device_pixel_ratio, glyph, halo) -> QPixmap | None`:
  1. `data = asset_bytes(kind)`; return `None` if `data is None`.
  2. For `"symbolic"`, substitute `b"__HALO__"` and `b"__GLYPH__"` with the
     `#rrggbb` byte form of `halo`/`glyph`. A symbolic render with either colour
     omitted is a programming error and raises `ValueError`.
  3. `renderer = QSvgRenderer(QByteArray(data))`; return `None` if
     `not renderer.isValid()`.
  4. Allocate `QImage(px, px, Format_ARGB32_Premultiplied)`, fill transparent,
     paint with `RenderHint.Antialiasing`, `renderer.render(painter)`.
  5. Return `None` when `QGuiApplication.instance() is None`, **before** any
     `QPixmap` is constructed. Otherwise `pixmap = QPixmap.fromImage(image)`,
     `pixmap.setDevicePixelRatio(device_pixel_ratio)`, return `pixmap`.
- `color_icon()` builds a `QIcon` by adding, for every `(size, dpr)` pair,
  `_render("color", size, dpr, None, None)` rendered at `size * dpr` physical
  pixels with the given ratio. Sizes outside `SIZES` are not rendered; Qt scales
  from the nearest listed size, which is the accepted trade-off for shipping a
  fixed set rather than rendering on demand.
- `symbolic_icon(glyph, halo)` does the same with the two tokens.
- Either builder returns a **null** `QIcon` when no pixmap could be produced. It
  never raises and never aborts the process.
- `tray_colors(palette) -> (glyph, halo)`:

  | Condition                                        | glyph                  | halo      |
  |--------------------------------------------------|------------------------|-----------|
  | `contrast(Window, WindowText) >= 3.0`             | `WindowText`           | opposite of glyph |
  | otherwise, `Window.lightness() > 127`             | `#1c1c1c`              | `#ffffff` |
  | otherwise                                        | `#f2f2f2`              | `#1c1c1c` |

  "Opposite of glyph" means `#ffffff` when `glyph.lightness() < 128`, else
  `#1c1c1c`. `contrast` is the WCAG relative-luminance contrast ratio.
- `tray_icon(app=None)` resolves `app = app or QApplication.instance()`:

  | resolved `app` | result |
  |---|---|
  | not `None` | `symbolic_icon(*tray_colors(app.palette()))` |
  | `None`     | a null `QIcon` (no palette exists, and no `QPixmap` may be built) |

### 3.3 Packaging

`src/ai_manager/resources/__init__.py` (empty) makes `resources` a real
subpackage so `importlib.resources` works from both a source checkout
(`PYTHONPATH=src`) and an editable install. `pyproject.toml` gains:

```toml
[tool.setuptools.package-data]
ai_manager = ["resources/icons/*.svg"]
```

## 4. Integration

### 4.1 `src/ai_manager/main.py`

Call `app.setWindowIcon(color_icon())` immediately after the `QApplication` is
constructed. This covers the window titlebar and the taskbar icon. It does
**not** establish the launcher↔window grouping association — `main.py` already
calls `app.setDesktopFileName("ai-manager")`, and `StartupWMClass=ai-manager`
in the `.desktop` entry is what handles that.

### 4.2 `src/ai_manager/ui/system_tray.py`

```python
def _apply_icon(self) -> None:
    app = QApplication.instance()
    if app is None:
        return
    icon = tray_icon(app)
    if icon.isNull():
        icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    self._tray_icon.setIcon(icon)

def _on_palette_changed(self, palette: QPalette | None = None) -> None:
    self._apply_icon()
```

`__init__` connects `app.paletteChanged` to `_on_palette_changed` when
`QApplication.instance()` is not `None`. The optional `palette` parameter
matches the signal's signature while keeping the slot callable with no
arguments from tests. The connection is never explicitly disconnected: the
manager is parented to `MainWindow`, which lives for the whole application
lifetime, and Qt destroys the connection with the objects. `_apply_icon()` is
idempotent, so repeated `paletteChanged` emissions (which can fire during
startup and theme transitions) are harmless, if briefly wasteful — eight sizes
times two DPRs are re-rasterised per emission. `app.windowIcon()` is no longer
consulted.

### 4.3 `src/ai_manager/services/desktop_integration.py`

`generate_desktop_entry()` writes `Icon={icon_value}`, where `icon_value` is
`str(asset_path("color"))` when that is not `None`, else the literal theme name
`applications-development` so the entry stays valid. This module imports only
`ai_manager.resources.assets`; it gains **no** Qt or `ui` dependency.

## 5. Data Flow

```
ai_manager/resources/icons/*.svg
        │  assets.asset_bytes(kind)          (Qt-free)
        ▼
   bytes ──symbolic?──▶ substitute __GLYPH__ / __HALO__
        │
        ▼
   QSvgRenderer ──invalid──▶ None ──▶ null QIcon ──▶ SP_ComputerIcon fallback
        │ valid
        ▼
   QImage(px, px)
        │  QGuiApplication.instance() is None ──▶ None (never build QPixmap)
        ▼
   QPixmap + devicePixelRatio, for (size, dpr) in SIZES × DPRs
        │
        ▼
      QIcon ──▶ QSystemTrayIcon.setIcon()   (symbolic, palette tint+halo)
            ──▶ QApplication.setWindowIcon() (colour)
            └──▶ assets.asset_path("color") ──▶ .desktop Icon= absolute path
```

## 6. Error Handling

- A missing, unreadable or malformed SVG yields a null `QIcon`; it never raises
  and never aborts. The tray keeps its existing `SP_ComputerIcon` fallback; the
  window simply has no icon.
- With no `QGuiApplication`, icon builders return a null `QIcon` without
  constructing a `QPixmap` (which would abort the process).
- `asset_bytes`/`asset_path` return `None` rather than raising, so
  `generate_desktop_entry()`/`install_desktop_shortcut()` cannot fail because an
  asset is missing; the entry falls back to a valid theme icon name.
- An unknown `kind` raises `ValueError` — the one deliberate hard failure, so a
  typo surfaces in tests instead of silently producing a null icon.
- `paletteChanged` is connected only when a `QApplication` exists, and the slot
  is safe to call with or without a palette argument.

## 7. Testing

New `tests/test_icons.py`, headless via the existing
`QT_QPA_PLATFORM=offscreen` in `conftest.py` and the pytest-qt `qapp` fixture:

1. Both assets exist and parse: `QSvgRenderer` reports `isValid()` for the
   colour asset and for the symbolic template after token substitution.
2. `color_icon()` is not null; `pixmap(QSize(22, 22))` is not null;
   `availableSizes()` contains `16`, `22` and `256`.
3. **Falsifiable tint test.** Render `symbolic_icon(QColor("#dd2222"),
   QColor("#22dd22"))` at 22px and assert: the corner pixel `(0, 0)` is
   transparent; the count of fully opaque pixels is between 15% and 60% of the
   canvas (so a solid square fails); and no opaque pixel is `#000000` or any
   colour other than the two tokens. This fails on the source/destination
   inversion bug (which leaves `#000000`), on a `SourceOver` fill (100%
   coverage), and on a dropped tint.
4. **Falsifiable halo test.** Render the symbolic icon with glyph `#1c1c1c` and
   halo `#ffffff` over a `#1c1c1c` panel and assert at least one pixel has
   contrast ratio `> 4.5` against the panel. This fails if the halo layer is
   removed, which is exactly the regression it exists to prevent.
5. `tray_colors()`: a light `QPalette` yields a dark glyph and white halo; a
   dark palette yields a light glyph and dark halo; a palette whose `Window` and
   `WindowText` are identical exercises the low-contrast guard branch and still
   returns opposite-luminance glyph/halo. Palettes are constructed directly.
6. `asset_path("color")` and `asset_path("symbolic")` return existing files;
   `asset_path("bogus")` raises `ValueError`.
7. Missing-asset path: monkeypatch `assets.asset_bytes` to return `None` and
   assert `color_icon().isNull()` and `symbolic_icon(...).isNull()`, with no
   exception.
8. Malformed asset: monkeypatch `assets.asset_bytes` to return
   `b"<svg"` and assert a null icon, not a raise.
9. **No-application test.** Run `sys.executable -c "..."` in a subprocess with
   no `QApplication`, importing `ai_manager.ui.icons` and calling
   `color_icon()` and `tray_icon(None)`. Assert exit code `0` and that both
   report `isNull()`. This is the regression test for the `QPixmap` abort.

Additions to existing tests:

- `tests/test_desktop_integration.py:86` currently asserts
  `"Icon=utilities-system-monitor" in content`, which **must be replaced**: the
  new assertion is that the `Icon=` line equals `str(asset_path("color"))` and
  that the path exists. A second test monkeypatches `asset_path` to `None` and
  asserts the `applications-development` fallback.
- `tests/test_system_tray.py`: after constructing `SystemTrayManager()`,
  `manager._tray_icon.icon().isNull()` is `False`; and monkeypatching
  `ai_manager.ui.system_tray.tray_icon` to count calls, emitting
  `qapp.paletteChanged` increments the count (the runtime re-tint contract).

## 8. Out of Scope / Known Caveats

- The `.desktop` entry keeps an **absolute** icon path, so it breaks if the
  installation moves, and it is resolved by whichever interpreter runs
  `generate_desktop_entry()` (source checkout, editable install, or
  site-packages). It is valid only when the same installation later launches the
  app. This matches the existing absolute `Exec=`/`Path=` fields; installing
  into `hicolor` under a themed name is deliberately deferred.
- An entry generated from inside a PM integration worktree points at that
  worktree and dies with it; such entries are test artifacts only.
- The already-installed `~/.local/share/applications/ai-manager.desktop`
  (`Icon=utilities-system-monitor`) only picks up the new icon when the shortcut
  is re-installed from the Settings dialog. Existing user entries are not
  rewritten on startup.
- `pyproject.toml` declares `authors = [{ name = "Henry", email =
  "henry@local" }]`, which fails setuptools 81 `idn-email` validation, so
  `pip install -e .` and wheel builds fail before package data is exercised.
  This is a **pre-existing** defect, unrelated to the icon work, and is recorded
  here only so the packaging claim is not overstated; it is not fixed by this
  plan.
- Only the sizes in `SIZES` are rasterised. Qt scales from the nearest listed
  size for any other device-pixel request.
- No light/dark variants of the colour asset are produced; the two-tone blue is
  used unchanged for window and launcher.
- Plasma's own symbolic recolouring is not used, so third-party
  monochrome-override behaviour does not apply.

## 9. Review Disposition

Revision 1 findings and where they are resolved.

| Finding | Resolution |
|---|---|
| M1 constraint factually wrong | §1.1 rewritten; the false claim is withdrawn and the `QSvgRenderer` rationale restated as control, not plugin absence |
| M2 tint test not falsifiable | §7.3 rebuilt around transparency, coverage fraction, and absence of any third colour |
| M3 `icon_path` wrong seam | §3.1 moves path/byte resolution into the Qt-free `ai_manager.resources.assets`; §4.3 imports only that |
| M4 tray tint vs panel | §1.2 + two-tone glyph/halo in §2.2 and §3.2; §7.4 pins it with a falsifiable contrast test |
| M5 untested re-tint / slot contract | §4.2 fixes the `_on_palette_changed(self, palette=None)` signature and connection lifetime; §7 adds the emission test |
| M6 `QPixmap` abort with no app | §3.2 returns before `QPixmap` construction; §6 states the contract; §7.9 adds a subprocess regression test |
| m1 stale existing assertion | §7 explicitly replaces `tests/test_desktop_integration.py:86` |
| m2 `icon_path` unguarded | §3.1 returns `None`; §4.3 falls back to `applications-development` |
| m3 DPR + SVG profile limits | §1.1 records the Tiny 1.2 limit; §3.2 adds `DEVICE_PIXEL_RATIOS`; §3.2/§8 document fixed-size scaling |
| m4 StartupWMClass wording | §4.1 corrected; grouping is attributed to `setDesktopFileName` |
| m5 pyproject metadata defect | §8 records it as pre-existing and explicitly out of scope |
| m6 missing tests | §7 items 7, 8, 9 and the `tray_colors` guard case in item 5 |
| m7 `tray_icon`/`kind` ambiguity | §3.2 branch table; §3.1 unknown `kind` raises `ValueError` |
| m8 `Icon=` install identity | §5 and §8 record the same-install and worktree-lifetime assumptions |
