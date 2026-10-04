import os
from PIL import Image, ImageDraw, ImageFont

# Canvas dimensions
WIDTH, HEIGHT = 1120, 760
img = Image.new("RGBA", (WIDTH, HEIGHT), (22, 24, 29, 255))
draw = ImageDraw.Draw(img)

# Try loading system font, fallback to default
try:
    font_title = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Bold.ttf", 17)
    font_section = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Bold.ttf", 14)
    font_body = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Regular.ttf", 13)
    font_bold = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Bold.ttf", 13)
    font_small = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Regular.ttf", 11)
except Exception:
    font_title = ImageFont.load_default()
    font_section = ImageFont.load_default()
    font_body = ImageFont.load_default()
    font_bold = ImageFont.load_default()
    font_small = ImageFont.load_default()

# Colors (matching ai-manager dark theme)
BG_DIALOG = (30, 34, 42, 255)
BORDER_COLOR = (55, 62, 76, 255)
PRIMARY_ACCENT = (59, 130, 246, 255) # Modern Blue
TEXT_MAIN = (240, 243, 246, 255)
TEXT_MUTED = (148, 163, 184, 255)
CARD_BG = (38, 43, 54, 255)
SUCCESS_GREEN = (34, 197, 94, 255)
BTN_BG = (51, 65, 85, 255)

# --- 1. SETTINGS DIALOG (LEFT / CENTER) ---
D_X, D_Y, D_W, D_H = 50, 45, 660, 665

# Dialog Shadow & Body
draw.rounded_rectangle([D_X+6, D_Y+6, D_X+D_W+6, D_Y+D_H+6], radius=10, fill=(10, 11, 14, 160))
draw.rounded_rectangle([D_X, D_Y, D_X+D_W, D_Y+D_H], radius=10, fill=BG_DIALOG, outline=BORDER_COLOR, width=1)

# Titlebar
draw.rounded_rectangle([D_X, D_Y, D_X+D_W, D_Y+46], radius=10, fill=(36, 41, 51, 255))
draw.rectangle([D_X, D_Y+36, D_X+D_W, D_Y+46], fill=(36, 41, 51, 255))
draw.text((D_X+20, D_Y+13), "⚙  Application Settings", font=font_title, fill=TEXT_MAIN)
draw.text((D_X+D_W-32, D_Y+13), "✕", font=font_title, fill=TEXT_MUTED)

# Section 1: System Integration
Y_CUR = D_Y + 65
draw.text((D_X+24, Y_CUR), "System Integration", font=font_section, fill=PRIMARY_ACCENT)
draw.line([D_X+24, Y_CUR+24, D_X+D_W-24, Y_CUR+24], fill=BORDER_COLOR, width=1)

Y_CUR += 38
# Checkbox 1: Close to tray
draw.rounded_rectangle([D_X+28, Y_CUR, D_X+46, Y_CUR+18], radius=4, fill=PRIMARY_ACCENT)
draw.text((D_X+32, Y_CUR+1), "✓", font=font_bold, fill=(255, 255, 255, 255))
draw.text((D_X+58, Y_CUR), "Minimize to system tray when closing window [X]", font=font_body, fill=TEXT_MAIN)

Y_CUR += 34
# Checkbox 2: Start minimized
draw.rounded_rectangle([D_X+28, Y_CUR, D_X+46, Y_CUR+18], radius=4, fill=CARD_BG, outline=BORDER_COLOR, width=1)
draw.text((D_X+58, Y_CUR), "Start minimized to system tray", font=font_body, fill=TEXT_MAIN)

Y_CUR += 34
# Checkbox 3: Run on system startup
draw.rounded_rectangle([D_X+28, Y_CUR, D_X+46, Y_CUR+18], radius=4, fill=PRIMARY_ACCENT)
draw.text((D_X+32, Y_CUR+1), "✓", font=font_bold, fill=(255, 255, 255, 255))
draw.text((D_X+58, Y_CUR), "Run on system startup (Autostart)", font=font_body, fill=TEXT_MAIN)
draw.text((D_X+58, Y_CUR+20), "Creates ~/.config/autostart/ai-manager.desktop with launcher wrapper", font=font_small, fill=TEXT_MUTED)

# Section 2: Desktop Shortcut & Plasma Start Menu
Y_CUR += 58
draw.text((D_X+24, Y_CUR), "Desktop & Application Menu", font=font_section, fill=PRIMARY_ACCENT)
draw.line([D_X+24, Y_CUR+24, D_X+D_W-24, Y_CUR+24], fill=BORDER_COLOR, width=1)

Y_CUR += 38
draw.rounded_rectangle([D_X+24, Y_CUR, D_X+D_W-24, Y_CUR+82], radius=8, fill=CARD_BG, outline=BORDER_COLOR, width=1)
draw.text((D_X+40, Y_CUR+16), "Start Menu Status:", font=font_bold, fill=TEXT_MAIN)
draw.rounded_rectangle([D_X+170, Y_CUR+12, D_X+340, Y_CUR+36], radius=4, fill=(20, 83, 45, 200), outline=SUCCESS_GREEN, width=1)
draw.text((D_X+180, Y_CUR+15), "● Installed in Launcher", font=font_small, fill=(187, 247, 208, 255))

# Buttons
draw.rounded_rectangle([D_X+40, Y_CUR+46, D_X+230, Y_CUR+72], radius=4, fill=BTN_BG, outline=BORDER_COLOR, width=1)
draw.text((D_X+55, Y_CUR+51), "Update Desktop Shortcut", font=font_small, fill=TEXT_MAIN)

draw.rounded_rectangle([D_X+245, Y_CUR+46, D_X+390, Y_CUR+72], radius=4, fill=(70, 30, 30, 255), outline=(150, 50, 50, 255), width=1)
draw.text((D_X+260, Y_CUR+51), "Remove Shortcut", font=font_small, fill=(254, 202, 202, 255))

# Section 3: General Preferences
Y_CUR += 105
draw.text((D_X+24, Y_CUR), "General Preferences", font=font_section, fill=PRIMARY_ACCENT)
draw.line([D_X+24, Y_CUR+24, D_X+D_W-24, Y_CUR+24], fill=BORDER_COLOR, width=1)

Y_CUR += 38
draw.text((D_X+32, Y_CUR+5), "Theme:", font=font_body, fill=TEXT_MAIN)
draw.rounded_rectangle([D_X+160, Y_CUR, D_X+300, Y_CUR+30], radius=4, fill=CARD_BG, outline=BORDER_COLOR, width=1)
draw.text((D_X+175, Y_CUR+6), "Dark Theme   ▾", font=font_body, fill=TEXT_MAIN)

Y_CUR += 40
draw.text((D_X+32, Y_CUR+5), "Polling Interval:", font=font_body, fill=TEXT_MAIN)
draw.rounded_rectangle([D_X+160, Y_CUR, D_X+300, Y_CUR+30], radius=4, fill=CARD_BG, outline=BORDER_COLOR, width=1)
draw.text((D_X+175, Y_CUR+6), "4000 ms      ▾", font=font_body, fill=TEXT_MAIN)

# Dialog Bottom Buttons
draw.line([D_X, D_Y+D_H-60, D_X+D_W, D_Y+D_H-60], fill=BORDER_COLOR, width=1)

draw.rounded_rectangle([D_X+D_W-230, D_Y+D_H-46, D_X+D_W-135, D_Y+D_H-14], radius=5, fill=CARD_BG, outline=BORDER_COLOR, width=1)
draw.text((D_X+D_W-205, D_Y+D_H-36), "Cancel", font=font_body, fill=TEXT_MUTED)

draw.rounded_rectangle([D_X+D_W-120, D_Y+D_H-46, D_X+D_W-20, D_Y+D_H-14], radius=5, fill=PRIMARY_ACCENT)
draw.text((D_X+D_W-105, D_Y+D_H-36), "Save & Apply", font=font_bold, fill=(255, 255, 255, 255))


# --- 2. SYSTEM TRAY & CONTEXT MENU (RIGHT SIDE) ---
T_X, T_Y, T_W = 760, 110, 310

# Panel Header
draw.text((T_X, 60), "System Tray Integration", font=font_section, fill=(255, 255, 255, 255))
draw.text((T_X, 83), "KDE Plasma / StatusNotifierItem", font=font_small, fill=TEXT_MUTED)

# Tray Context Menu
draw.rounded_rectangle([T_X+6, T_Y+6, T_X+T_W+6, T_Y+306], radius=8, fill=(10, 11, 14, 160))
draw.rounded_rectangle([T_X, T_Y, T_X+T_W, T_Y+300], radius=8, fill=(32, 36, 45, 255), outline=BORDER_COLOR, width=1)

MENU_ITEMS = [
    ("Show ai-manager", False, font_bold, TEXT_MAIN),
    ("---", False, None, None),
    ("Start All Supervised Services", False, font_body, TEXT_MAIN),
    ("Stop All Supervised Services", False, font_body, TEXT_MAIN),
    ("---", False, None, None),
    ("⚙  Settings...", False, font_body, TEXT_MAIN),
    ("---", False, None, None),
    ("✕  Quit ai-manager", False, font_body, (248, 113, 113, 255))
]

M_Y = T_Y + 14
for label, active, font, col in MENU_ITEMS:
    if label == "---":
        draw.line([T_X+10, M_Y+5, T_X+T_W-10, M_Y+5], fill=BORDER_COLOR, width=1)
        M_Y += 12
    else:
        draw.text((T_X+20, M_Y+4), label, font=font, fill=col)
        M_Y += 34

# First-Close Tray Notification Bubble
B_Y = T_Y + 330
draw.rounded_rectangle([T_X+4, B_Y+4, T_X+T_W+4, B_Y+144], radius=8, fill=(10, 11, 14, 140))
draw.rounded_rectangle([T_X, B_Y, T_X+T_W, B_Y+140], radius=8, fill=(35, 41, 52, 255), outline=PRIMARY_ACCENT, width=1)

draw.text((T_X+16, B_Y+16), "💬  ai-manager running in tray", font=font_bold, fill=(255, 255, 255, 255))
draw.text((T_X+16, B_Y+44), "The application will keep supervising\nservices in the background.\nClick the tray icon to restore or quit.", font=font_small, fill=TEXT_MUTED)

out_path = "/data/home/guest/Development/ai/ai-manager/docs/superpowers/specs/mockups/system_tray_settings_mockup.png"
os.makedirs(os.path.dirname(out_path), exist_ok=True)
img.save(out_path)
print("Successfully generated mockup at:", out_path)
