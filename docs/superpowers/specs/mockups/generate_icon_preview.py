"""Render the ai-manager icon preview used in the icon design document.

Self-contained: builds the hub geometry in memory, renders it with
QSvgRenderer at every supported size on light and dark backgrounds, and writes
``app_icon_preview.png`` next to this file. Also exercises the tint path that
the design document warns about (painting the tint as the *source* with
CompositionMode_SourceIn, over the icon as the *destination*).

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

R, HUB, SAT, STROKE, ROT = 7.1, 3.5, 2.0, 1.5, 90
DY = 1.5
SIZES = (16, 22, 32, 48, 64, 128)
ZOOM = 6
LIGHT = (240, 240, 240, 255)
DARK = (24, 24, 31, 255)

COLOR_MAIN, COLOR_SAT = "#3B82F6", "#60A5FA"


def hub_svg(main: str, sat: str) -> bytes:
    """The canonical orchestration-hub geometry from the design document."""
    pts = [
        (
            12 + R * math.cos(math.radians(ROT + i * 120)),
            12 - R * math.sin(math.radians(ROT + i * 120)) + DY,
        )
        for i in range(3)
    ]
    cy = 12 + DY
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">',
        f'<g stroke="{main}" stroke-width="{STROKE}" stroke-linecap="round">',
    ]
    for x, y in pts:
        lines.append(f'<line x1="12" y1="{cy}" x2="{x:.2f}" y2="{y:.2f}"/>')
    lines.append("</g>")
    lines.append(f'<g fill="{sat}">')
    for x, y in pts:
        lines.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{SAT}"/>')
    lines.append("</g>")
    lines.append(f'<circle cx="12" cy="{cy}" r="{HUB}" fill="{main}"/></svg>')
    return "\n".join(lines).encode("utf-8")


def render(svg: bytes, px: int, tint: str | None = None, bg=LIGHT) -> Image.Image:
    renderer = QSvgRenderer(svg)
    assert renderer.isValid(), "generated SVG did not parse"
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    if tint:
        # Tint as SOURCE over the icon as DESTINATION.
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(image.rect(), QColor(tint))
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


def _font(size: int, bold: bool = False):
    name = "NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf"
    try:
        return ImageFont.truetype(f"/usr/share/fonts/noto/{name}", size)
    except Exception:
        return ImageFont.load_default()


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


def main() -> None:
    app = QApplication([])
    color = hub_svg(COLOR_MAIN, COLOR_SAT)
    symbolic = hub_svg("#000000", "#000000")

    # Prove the tint path actually recolours (guards the source/destination bug).
    check = render(symbolic, 22, tint="#f2f2f2", bg=DARK)
    assert check.getpixel((11, 11))[:3] == (242, 242, 242), check.getpixel((11, 11))

    rows = [
        ("color — light panel", color, None, LIGHT),
        ("color — dark panel", color, None, DARK),
        ("symbolic #1c1c1c — light panel", symbolic, "#1c1c1c", LIGHT),
        ("symbolic #f2f2f2 — dark panel", symbolic, "#f2f2f2", DARK),
    ]

    f, f_bold = _font(12), _font(13, bold=True)
    sheet = Image.new("RGBA", (1000, 30 + len(rows) * 175 + 210), (250, 250, 252, 255))
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 10), "ai-manager orchestration hub — canonical geometry", font=f_bold, fill=(15, 15, 15))
    y = 34
    for label, svg, tint, bg in rows:
        draw.text((16, y + 64), label, font=f_bold, fill=(30, 30, 30))
        x = 300
        for size in SIZES:
            img = render(svg, size, tint=tint, bg=bg)
            sheet.paste(img, (x, y), img)
            draw.rectangle([x - 1, y - 1, x + size, y + size], outline=(185, 185, 185))
            draw.text((x + 2, y + size + 2), str(size), font=f, fill=(110, 110, 110))
            x += size + 16
        y += 175

    y += 6
    draw.text((16, y), "22px tray size @6x, versus the current SP_ComputerIcon fallback:", font=f_bold, fill=(30, 30, 30))
    y += 20
    x = 16
    for _label, svg, tint, bg in rows:
        img = render(svg, 22, tint=tint, bg=bg).resize((132, 132), Image.NEAREST)
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
