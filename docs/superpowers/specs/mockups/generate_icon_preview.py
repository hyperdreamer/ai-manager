"""Render the ai-manager icon preview used in the icon design document.

Self-contained: builds the hub geometry in memory, renders it with
QSvgRenderer at every supported size, and writes ``app_icon_preview.png`` next
to this file. Covers the colour asset plus the two-tone symbolic asset on both
matching and mismatched panels, and the current ``SP_ComputerIcon`` fallback.

Run with the project interpreter (needs PyQt6 + Pillow):

    /home/henry/anaconda3/envs/daily/bin/python generate_icon_preview.py
"""

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt6.QtSvg import QSvgRenderer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QStyle  # noqa: E402

# Canonical geometry, mirrored from the design document section 2.1.
R, HUB, SAT, STROKE, ROT = 7.1, 3.5, 2.0, 1.5, 90
DY = 1.5
HALO = 0.8
SIZES = (16, 22, 32, 48, 64, 128)
ZOOM = 6
LIGHT = (240, 240, 240, 255)
DARK = (24, 24, 31, 255)

COLOR_MAIN, COLOR_SAT = "#3B82F6", "#60A5FA"
GLYPH, HALO_COLOR = "#1c1c1c", "#ffffff"

_SATELLITES = [
    (
        12 + R * math.cos(math.radians(ROT + i * 120)),
        12 - R * math.sin(math.radians(ROT + i * 120)) + DY,
    )
    for i in range(3)
]
_CY = 12 + DY


def hub_svg(main: str, sat: str) -> bytes:
    """Full-colour asset: two-tone, no halo."""
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">',
        f'<g stroke="{main}" stroke-width="{STROKE}" stroke-linecap="round">',
    ]
    for x, y in _SATELLITES:
        lines.append(f'<line x1="12" y1="{_CY}" x2="{x:.2f}" y2="{y:.2f}"/>')
    lines.append("</g>")
    lines.append(f'<g fill="{sat}">')
    for x, y in _SATELLITES:
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{SAT}"/>')
    lines.append("</g>")
    lines.append(f'<circle cx="12" cy="{_CY}" r="{HUB}" fill="{main}"/></svg>')
    return "\n".join(lines).encode("utf-8")


def hub_svg_symbolic(glyph: str, halo: str | None) -> bytes:
    """Two-tone symbolic asset: halo layer under the glyph layer.

    ``halo=None`` omits the halo layer entirely and produces the control render
    that demonstrates why the halo is required on a mismatched panel.
    """
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">',
    ]
    if halo is not None:
        # halo layer, expanded by HALO on every edge
        lines.append(f'<g stroke="{halo}" stroke-width="{STROKE + 2 * HALO}" stroke-linecap="round">')
        for x, y in _SATELLITES:
            lines.append(f'<line x1="12" y1="{_CY}" x2="{x:.2f}" y2="{y:.2f}"/>')
        lines.append("</g>")
        lines.append(f'<g fill="{halo}">')
        for x, y in _SATELLITES:
            lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{SAT + HALO}"/>')
        lines.append(f'<circle cx="12" cy="{_CY}" r="{HUB + HALO}"/></g>')
    # glyph layer
    lines.append(f'<g stroke="{glyph}" stroke-width="{STROKE}" stroke-linecap="round">')
    for x, y in _SATELLITES:
        lines.append(f'<line x1="12" y1="{_CY}" x2="{x:.2f}" y2="{y:.2f}"/>')
    lines.append("</g>")
    lines.append(f'<g fill="{glyph}">')
    for x, y in _SATELLITES:
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{SAT}"/>')
    lines.append(f'<circle cx="12" cy="{_CY}" r="{HUB}"/></g></svg>')
    return "\n".join(lines).encode("utf-8")


def render(svg: bytes, px: int, bg=LIGHT) -> Image.Image:
    renderer = QSvgRenderer(svg)
    assert renderer.isValid(), "generated SVG did not parse"
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    out = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(QColor(*bg[:3]))
    painter = QPainter(out)
    painter.drawImage(0, 0, image)
    painter.end()
    out = out.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = out.constBits()
    ptr.setsize(out.sizeInBytes())
    return Image.frombytes("RGBA", (px, px), bytes(ptr))


def standard_icon(app: QApplication, px: int, bg) -> Image.Image:
    """The current fallback: QStyle.SP_ComputerIcon."""
    pixmap = app.style().standardIcon(
        QStyle.StandardPixmap.SP_ComputerIcon
    ).pixmap(px, px)
    qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = qimage.constBits()
    ptr.setsize(qimage.sizeInBytes())
    icon = Image.frombytes("RGBA", (px, px), bytes(ptr))
    out = Image.new("RGBA", (px, px), bg)
    out.paste(icon, (0, 0), icon)
    return out


def _font(size: int, bold: bool = False):
    name = "NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf"
    try:
        return ImageFont.truetype(f"/usr/share/fonts/noto/{name}", size)
    except Exception:
        return ImageFont.load_default()


def main() -> None:
    app = QApplication([])
    color = hub_svg(COLOR_MAIN, COLOR_SAT)
    symbolic = hub_svg_symbolic(GLYPH, HALO_COLOR)
    no_halo = hub_svg_symbolic(GLYPH, None)

    # Prove the halo actually keeps the glyph legible on a same-colour panel.
    # Without the halo layer this assertion fails, which is its whole point.
    on_match = render(symbolic, 22, bg=(28, 28, 28))
    panel = (28, 28, 28)
    rgb = on_match.convert("RGB").tobytes()
    max_delta = max(
        max(abs(rgb[i] - panel[0]), abs(rgb[i + 1] - panel[1]), abs(rgb[i + 2] - panel[2]))
        for i in range(0, len(rgb), 3)
    )
    assert max_delta > 150, f"halo did not separate glyph from panel (delta={max_delta})"
    # The control must FAIL the same separation test; otherwise the assertion
    # above proves nothing about the halo.
    ctl = render(no_halo, 22, bg=(28, 28, 28)).convert("RGB").tobytes()
    ctl_delta = max(
        max(abs(ctl[i] - panel[0]), abs(ctl[i + 1] - panel[1]), abs(ctl[i + 2] - panel[2]))
        for i in range(0, len(ctl), 3)
    )
    assert ctl_delta < 40, f"without-halo control unexpectedly separated (delta={ctl_delta})"

    rows = [
        ("colour - light panel", color, LIGHT),
        ("colour - dark panel", color, DARK),
        ("symbolic glyph+halo - light panel", symbolic, LIGHT),
        ("symbolic glyph+halo - dark panel (halo carries it)", symbolic, DARK),
        ("CONTROL: symbolic without halo - dark panel", no_halo, DARK),
    ]

    f, f_bold = _font(12), _font(13, bold=True)
    sheet = Image.new("RGBA", (1000, 30 + len(rows) * 175 + 210), (250, 250, 252, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 10), "ai-manager orchestration hub - canonical geometry", font=f_bold, fill=(15, 15, 15))
    y = 34
    for label, svg, bg in rows:
        draw.text((16, y + 64), label, font=f_bold, fill=(30, 30, 30))
        x = 300
        for size in SIZES:
            img = render(svg, size, bg=bg)
            sheet.paste(img, (x, y), img)
            draw.rectangle([x - 1, y - 1, x + size, y + size], outline=(185, 185, 185))
            draw.text((x + 2, y + size + 2), str(size), font=f, fill=(110, 110, 110))
            x += size + 16
        y += 175

    y += 6
    draw.text((16, y), "22px tray size @6x, versus the current SP_ComputerIcon fallback:", font=f_bold, fill=(30, 30, 30))
    y += 20
    x = 16
    for _label, svg, bg in rows:
        img = render(svg, 22, bg=bg).resize((132, 132), Image.NEAREST)
        sheet.paste(img, (x, y), img)
        draw.rectangle([x - 1, y - 1, x + 132, y + 132], outline=(185, 185, 185))
        x += 150
    current = standard_icon(app, 22, DARK).resize((132, 132), Image.NEAREST)
    sheet.paste(current, (x, y), current)
    draw.rectangle([x - 1, y - 1, x + 132, y + 132], outline=(200, 60, 60), width=2)
    draw.text((x, y + 136), "<- current (SP_Computer)", font=f, fill=(200, 60, 60))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon_preview.png")
    sheet.save(out)
    print(f"wrote {out} {sheet.size}")


if __name__ == "__main__":
    main()
