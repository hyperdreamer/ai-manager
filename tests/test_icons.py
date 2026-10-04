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


def test_asset_path_returns_existing_files_and_rejects_unknown_kind():
    for kind in ("color", "symbolic"):
        path = assets.asset_path(kind)
        assert path is not None
        assert path.is_file()
    with pytest.raises(ValueError):
        assets.asset_path("bogus")


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


def test_symbolic_render_requires_both_colours(qapp):
    with pytest.raises(ValueError):
        icons._render("symbolic", 22, 1.0, None, QColor("#ffffff"))
    with pytest.raises(ValueError):
        icons._render("symbolic", 22, 1.0, QColor("#000000"), None)


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
    installed = manager._tray_icon.icon()
    assert not installed.isNull()
    # Pin the identity of the fallback, not merely that some icon is present:
    # any other standard icon would satisfy a bare non-null check.
    assert installed.pixmap(22, 22).toImage() == expected.pixmap(22, 22).toImage()
