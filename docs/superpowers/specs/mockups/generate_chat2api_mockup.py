"""Mockup generator for chat2api + file-bridge configuration surfaces.

Produces three option panels sharing the ai-manager dark palette.
"""
import sys
from PIL import Image, ImageDraw, ImageFont

W, H = 1180, 820
BG = (22, 24, 29, 255)
CARD = (30, 34, 42, 255)
CARD2 = (38, 43, 54, 255)
BORDER = (55, 62, 76, 255)
ACCENT = (59, 130, 246, 255)
TEXT = (240, 243, 246, 255)
MUTED = (148, 163, 184, 255)
GREEN = (34, 197, 94, 255)
AMBER = (245, 158, 11, 255)
RED = (239, 68, 68, 255)

try:
    f_title = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Bold.ttf", 16)
    f_sec = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Bold.ttf", 13)
    f_body = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Regular.ttf", 12)
    f_bold = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Bold.ttf", 12)
    f_small = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Regular.ttf", 10)
    f_mono = ImageFont.truetype("/usr/share/fonts/noto/NotoSansMono-Regular.ttf", 10)
except Exception:
    f_title = f_sec = f_body = f_bold = f_small = f_mono = ImageFont.load_default()


def rr(d, box, radius=6, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def field(d, x, y, w, label, value, h=26):
    d.text((x, y), label, font=f_small, fill=MUTED)
    rr(d, [x, y + 13, x + w, y + 13 + h], radius=4, fill=(24, 27, 34, 255), outline=BORDER)
    d.text((x + 8, y + 19), value, font=f_body, fill=TEXT)
    return y + 13 + h


def section(d, x, y, w, title):
    d.text((x, y), title, font=f_sec, fill=ACCENT)
    d.line([x, y + 19, x + w, y + 19], fill=BORDER, width=1)
    return y + 29


def btn(d, x, y, w, h, label, primary=False, danger=False):
    fill = ACCENT if primary else (CARD2 if not danger else (70, 32, 36, 255))
    rr(d, [x, y, x + w, y + h], radius=4, fill=fill, outline=BORDER)
    tw = d.textlength(label, font=f_bold)
    d.text((x + (w - tw) / 2, y + (h - 12) / 2), label, font=f_bold, fill=TEXT)


def chip(d, x, y, label, ok=True):
    col = GREEN if ok else AMBER
    tw = d.textlength(label, font=f_small)
    rr(d, [x, y, x + tw + 16, y + 17], radius=8, fill=(col[0] // 5, col[1] // 5, col[2] // 5, 255), outline=col)
    d.text((x + 8, y + 3), label, font=f_small, fill=col)
    return x + tw + 22


def tabrow(d, x, y, tabs, active=0):
    for i, t in enumerate(tabs):
        tw = d.textlength(t, font=f_bold) + 28
        fill = CARD2 if i == active else (0, 0, 0, 0)
        rr(d, [x, y, x + tw, y + 26], radius=4, fill=fill, outline=BORDER if i == active else None)
        d.text((x + 14, y + 7), t, font=f_bold, fill=TEXT if i == active else MUTED)
        x += tw + 4
    return y + 32


def frame(d, title, subtitle):
    d.rectangle([0, 0, W, H], fill=BG)
    d.text((20, 14), title, font=f_title, fill=TEXT)
    d.text((20, 36), subtitle, font=f_small, fill=MUTED)


# ---------------------------------------------------------------- option A
def option_a():
    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img)
    frame(d, "OPTION A — Single scrollable page, grouped sections", "chat2api · sidebar entry + Configuration tab")

    # sidebar
    rr(d, [16, 56, 220, H - 16], radius=8, fill=CARD, outline=BORDER)
    d.text((28, 68), "ai-grammar", font=f_body, fill=MUTED)
    d.text((28, 92), "textkit", font=f_body, fill=MUTED)
    d.text((28, 116), "yt2txt", font=f_body, fill=MUTED)
    d.ellipse([26, 146, 34, 154], fill=GREEN)
    d.text((44, 142), "chat2api", font=f_bold, fill=TEXT)
    d.text((48, 160), "Port 8000", font=f_small, fill=MUTED)
    d.ellipse([26, 186, 34, 194], fill=GREEN)
    d.text((44, 182), "file-bridge", font=f_bold, fill=TEXT)
    d.text((48, 200), "Port 8964", font=f_small, fill=MUTED)
    d.text((28, 226), "free-tts", font=f_body, fill=MUTED)

    X, WD = 236, W - 252
    rr(d, [X, 56, X + WD, H - 16], radius=8, fill=CARD, outline=BORDER)
    d.text((X + 18, 68), "chat2api", font=f_title, fill=TEXT)
    d.text((X + 18, 88), "Local OpenAI-compatible gateway (Gemini / M365 Copilot)", font=f_small, fill=MUTED)
    chip(d, X + WD - 300, 70, "running pid=42974")
    btn(d, X + WD - 130, 66, 112, 24, "Restart Service")

    y = tabrow(d, X + 18, 112, ["Configuration", "Logs"])

    # status strip about which file is edited
    rr(d, [X + 18, y + 6, X + WD - 18, y + 38], radius=4, fill=(24, 27, 34, 255), outline=BORDER)
    d.text((X + 28, y + 14), "Editing", font=f_small, fill=MUTED)
    d.text((X + 76, y + 13), "/data/home/guest/Development/ai/chat2api/config.json", font=f_mono, fill=TEXT)
    d.text((X + WD - 210, y + 14), "validated by chat2api loader", font=f_small, fill=GREEN)
    y += 52

    y = section(d, X + 18, y, WD - 36, "Server")
    y = field(d, X + 18, y, 150, "Host", "127.0.0.1") + 10
    y = field(d, X + 182, y - 36, 110, "Port", "8000") + 10
    y = field(d, X + 306, y - 46, 240, "Auth token env var", "CHAT2API_TOKEN") + 22

    y = section(d, X + 18, y, WD - 36, "Models")
    d.text((X + 18, y - 4), "Routing table — name maps to a provider and its options.", font=f_small, fill=MUTED)
    y += 18
    rows = [
        ("gemini", "gemini_webapi", "account, password", 1),
        ("m365-copilot", "copilot_webapi", "account, password", 1),
        ("browser-gemini", "browser", "headless", 0),
        ("echo-1", "echo", "—", 0),
    ]
    hdr_y = y
    for cx, lab in ((X + 26, "NAME"), (X + 150, "PROVIDER"), (X + 300, "OPTIONS"), (X + 560, "SECRETS")):
        d.text((cx, hdr_y), lab, font=f_small, fill=MUTED)
    y += 16
    d.line([X + 18, y, X + WD - 18, y], fill=BORDER)
    y += 6
    for name, prov, opts, secret in rows:
        rr(d, [X + 18, y, X + WD - 18, y + 30], radius=4, fill=CARD2 if secret else None, outline=BORDER if secret else None)
        d.text((X + 26, y + 9), name, font=f_mono, fill=TEXT)
        d.text((X + 150, y + 9), prov, font=f_mono, fill=ACCENT)
        d.text((X + 300, y + 9), opts, font=f_mono, fill=MUTED)
        if secret:
            rr(d, [X + 560, y + 6, X + 700, y + 24], radius=3, fill=(24, 27, 34, 255), outline=BORDER)
            d.text((X + 568, y + 9), "••••••••••••", font=f_mono, fill=TEXT)
            btn(d, X + 712, y + 5, 62, 20, "Reveal")
        else:
            d.text((X + 560, y + 9), "none", font=f_small, fill=MUTED)
        btn(d, X + WD - 96, y + 5, 70, 20, "Remove")
        y += 36
    btn(d, X + 18, y + 4, 120, 24, "+ Add model")

    # footer
    d.line([X + 18, H - 62, X + WD - 18, H - 62], fill=BORDER)
    d.text((X + 18, H - 50), "● Unsaved changes", font=f_small, fill=AMBER)
    btn(d, X + WD - 340, H - 56, 150, 28, "Save Config Only")
    btn(d, X + WD - 180, H - 56, 162, 28, "Save and Restart", primary=True)
    img.save("/tmp/c2a_mock/option_a.png")


# ---------------------------------------------------------------- option B
def option_b():
    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img)
    frame(d, "OPTION B — Sub-tabbed configuration (Server / Models)", "chat2api · Configuration split into two sub-tabs")

    rr(d, [16, 56, 220, H - 16], radius=8, fill=CARD, outline=BORDER)
    d.ellipse([26, 70, 34, 78], fill=GREEN)
    d.text((44, 66), "chat2api", font=f_bold, fill=TEXT)
    d.ellipse([26, 96, 34, 104], fill=GREEN)
    d.text((44, 92), "file-bridge", font=f_bold, fill=TEXT)

    X, WD = 236, W - 252
    rr(d, [X, 56, X + WD, H - 16], radius=8, fill=CARD, outline=BORDER)
    d.text((X + 18, 68), "chat2api", font=f_title, fill=TEXT)
    chip(d, X + WD - 300, 70, "running pid=42974")
    btn(d, X + WD - 130, 66, 112, 24, "Restart Service")

    y = tabrow(d, X + 18, 112, ["Configuration", "Logs"])
    # nested tabs
    x2 = X + 18
    for i, t in enumerate(["Server", "Models  (4)", "Raw JSON"]):
        tw = d.textlength(t, font=f_bold) + 26
        rr(d, [x2, y + 6, x2 + tw, y + 30], radius=14, fill=ACCENT if i == 1 else CARD2, outline=BORDER)
        d.text((x2 + 13, y + 12), t, font=f_bold, fill=TEXT)
        x2 += tw + 6
    y += 46

    d.text((X + 18, y), "Models", font=f_sec, fill=TEXT)
    d.text((X + 18, y + 18), "Each model name is exposed on /v1/models. Provider options are provider-specific.", font=f_small, fill=MUTED)
    btn(d, X + WD - 150, y - 2, 132, 24, "+ Add model")

    y += 44
    for name, prov, secret in [
        ("gemini", "gemini_webapi", True),
        ("m365-copilot", "copilot_webapi", True),
        ("browser-gemini", "browser", False),
        ("echo-1", "echo", False),
    ]:
        rr(d, [X + 18, y, X + WD - 18, y + 116], radius=6, fill=CARD2, outline=BORDER)
        d.text((X + 32, y + 12), name, font=f_bold, fill=TEXT)
        d.text((X + 150, y + 13), "provider", font=f_small, fill=MUTED)
        rr(d, [X + 210, y + 6, X + 350, y + 30], radius=4, fill=(24, 27, 34, 255), outline=BORDER)
        d.text((X + 220, y + 10), prov, font=f_mono, fill=ACCENT)
        btn(d, X + WD - 96, y + 8, 70, 22, "Remove")

        if secret:
            d.text((X + 32, y + 44), "account", font=f_small, fill=MUTED)
            rr(d, [X + 32, y + 58, X + 250, y + 82], radius=4, fill=(24, 27, 34, 255), outline=BORDER)
            d.text((X + 40, y + 62), "a215400@siswa.ukm.edu.my", font=f_mono, fill=TEXT)
            d.text((X + 270, y + 44), "password", font=f_small, fill=MUTED)
            rr(d, [X + 270, y + 58, X + 450, y + 82], radius=4, fill=(24, 27, 34, 255), outline=BORDER)
            d.text((X + 278, y + 62), "••••••••••••••", font=f_mono, fill=TEXT)
            btn(d, X + 460, y + 59, 62, 22, "Reveal")
            chip(d, X + 534, y + 61, "stored in plaintext", ok=False)
        else:
            d.text((X + 32, y + 44), "headless", font=f_small, fill=MUTED)
            rr(d, [X + 32, y + 58, X + 60, y + 74], radius=3, fill=ACCENT)
            d.text((X + 38, y + 60), "✓", font=f_bold, fill=(255, 255, 255, 255))
            d.text((X + 70, y + 58), "run browser headless", font=f_small, fill=TEXT)
        y += 124

    d.line([X + 18, H - 62, X + WD - 18, H - 62], fill=BORDER)
    d.text((X + 18, H - 50), "● Unsaved changes", font=f_small, fill=AMBER)
    btn(d, X + WD - 340, H - 56, 150, 28, "Save Config Only")
    btn(d, X + WD - 180, H - 56, 162, 28, "Save and Restart", primary=True)
    img.save("/tmp/c2a_mock/option_b.png")


# ---------------------------------------------------------------- option C
def option_c():
    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img)
    frame(d, "OPTION C — Split pane: form left, live file preview right", "chat2api · side-by-side diff preview before save")

    rr(d, [16, 56, 220, H - 16], radius=8, fill=CARD, outline=BORDER)
    d.ellipse([26, 70, 34, 78], fill=GREEN)
    d.text((44, 66), "chat2api", font=f_bold, fill=TEXT)
    d.ellipse([26, 96, 34, 104], fill=GREEN)
    d.text((44, 96 - 10), "file-bridge", font=f_bold, fill=TEXT)

    X, WD = 236, W - 252
    rr(d, [X, 56, X + WD, H - 16], radius=8, fill=CARD, outline=BORDER)
    d.text((X + 18, 68), "chat2api", font=f_title, fill=TEXT)
    chip(d, X + WD - 300, 70, "running pid=42974")
    y = tabrow(d, X + 18, 100, ["Configuration", "Logs"])

    LW = int((WD - 54) * 0.52)
    RX = X + 18 + LW + 18
    RW = WD - 36 - LW - 18

    d.text((X + 18, y + 4), "Server", font=f_sec, fill=ACCENT)
    y1 = y + 26
    y1 = field(d, X + 18, y1, LW, "Host", "127.0.0.1") + 8
    y1 = field(d, X + 18, y1, 110, "Port", "8000") + 8
    y1 = field(d, X + 18, y1, LW, "Auth token env var", "CHAT2API_TOKEN") + 16

    d.text((X + 18, y1), "Models", font=f_sec, fill=ACCENT)
    y1 += 22
    for name, prov in [("gemini", "gemini_webapi"), ("m365-copilot", "copilot_webapi"), ("browser-gemini", "browser")]:
        rr(d, [X + 18, y1, X + 18 + LW, y1 + 30], radius=4, fill=CARD2, outline=BORDER)
        d.text((X + 28, y1 + 9), name, font=f_mono, fill=TEXT)
        d.text((X + 130, y1 + 9), prov, font=f_mono, fill=ACCENT)
        d.text((X + 18 + LW - 22, y1 + 8), "›", font=f_bold, fill=MUTED)
        y1 += 36
    btn(d, X + 18, y1 + 2, 120, 24, "+ Add model")
    d.text((X + 18, y1 + 38), "Selecting a model opens its provider options", font=f_small, fill=MUTED)
    d.text((X + 18, y1 + 54), "inline below the row, including masked secrets.", font=f_small, fill=MUTED)

    # right: preview panel
    rr(d, [RX, y + 4, RX + RW, H - 76], radius=6, fill=(17, 19, 24, 255), outline=BORDER)
    d.text((RX + 12, y + 12), "config.json  —  pending changes", font=f_bold, fill=TEXT)
    chip(d, RX + RW - 96, y + 12, "3 changed")
    yy = y + 38
    code = [
        ('{', TEXT),
        ('  "server": {', TEXT),
        ('    "host": "127.0.0.1",', MUTED),
        ('    "port": 8000,', TEXT),
        ('+   "auth_token_env": "CHAT2API_TOKEN",', GREEN),
        ('  },', TEXT),
        ('  "models": {', TEXT),
        ('    "gemini": {', TEXT),
        ('      "provider": "gemini_webapi",', MUTED),
        ('      "options": {', MUTED),
        ('-       "password": "ftw***",', RED),
        ('+       "password": "New***",', GREEN),
        ('      }', MUTED),
        ('    },', MUTED),
        ('+   "echo-1": { "provider": "echo" },', GREEN),
        ('  }', TEXT),
        ('}', TEXT),
    ]
    for line, col in code:
        d.text((RX + 12, yy), line, font=f_mono, fill=col)
        yy += 15
    d.line([RX + 8, H - 106, RX + RW - 8, H - 106], fill=BORDER)
    d.text((RX + 12, H - 98), "Save blocks if the file changed on disk.", font=f_small, fill=MUTED)
    d.text((RX + 12, H - 84), "Backup written to config.json.<ts>.bak", font=f_small, fill=MUTED)

    d.line([X + 18, H - 62, X + WD - 18, H - 62], fill=BORDER)
    d.text((X + 18, H - 50), "● Unsaved changes", font=f_small, fill=AMBER)
    btn(d, X + WD - 340, H - 56, 150, 28, "Review Diff")
    btn(d, X + WD - 180, H - 56, 162, 28, "Save and Restart", primary=True)
    img.save("/tmp/c2a_mock/option_c.png")


if __name__ == "__main__":
    if "a" in sys.argv or len(sys.argv) == 1:
        option_a()
    if "b" in sys.argv or len(sys.argv) == 1:
        option_b()
    if "c" in sys.argv or len(sys.argv) == 1:
        option_c()
    print("written")
