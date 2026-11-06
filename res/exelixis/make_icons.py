#!/usr/bin/env python3
"""Regenerate all app icons and logos from res/exelixis/app-icon.jpg and exelixisnet-logo.png.
Run from the repository root: python3 res/exelixis/make_icons.py  (needs Pillow)"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
icon = Image.open(os.path.join(HERE, "app-icon.jpg")).convert("RGBA")
logo = Image.open(os.path.join(HERE, "exelixisnet-logo.png")).convert("RGBA")


def tile(size: int) -> Image.Image:
    """The Exelixisnet app icon with softly rounded corners."""
    big = size * 4
    img = icon.resize((big, big), Image.LANCZOS)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.18), fill=255)
    img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


def save_ico(path: str, sizes=(16, 24, 32, 48, 64, 128, 256)):
    base = tile(256)
    base.save(path, format="ICO", sizes=[(s, s) for s in sizes])


def out(rel):
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


tile(1024).save(out("res/icon.png"))
tile(1024).save(out("res/mac-icon.png"))
for s, name in [(32, "32x32.png"), (64, "64x64.png"), (128, "128x128.png"), (256, "128x128@2x.png")]:
    tile(s).save(out(f"res/{name}"))
save_ico(out("res/icon.ico"))
save_ico(out("res/tray-icon.ico"), sizes=(16, 20, 24, 32, 48, 64))
save_ico(out("flutter/windows/runner/resources/app_icon.ico"))
tile(256).save(out("flutter/assets/icon.png"))

# Home-page logo: the widget shows at most 300x60, so ship it at 3x for sharp HiDPI.
bb = logo.getbbox()
l = logo.crop(bb)
w = 900
l = l.resize((w, int(l.height * w / l.width)), Image.LANCZOS)
l.save(out("flutter/assets/logo.png"))

# Android launcher icons
for d, s in [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)]:
    p = os.path.join(ROOT, f"flutter/android/app/src/main/res/mipmap-{d}")
    if os.path.isdir(p):
        for f in os.listdir(p):
            if f.endswith(".png") and "launcher" in f and "foreground" not in f:
                tile(s).save(os.path.join(p, f))
print("icons written")
