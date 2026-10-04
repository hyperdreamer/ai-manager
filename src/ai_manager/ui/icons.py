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
