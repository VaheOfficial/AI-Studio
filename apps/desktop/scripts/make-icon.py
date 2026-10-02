"""Draws the app icon to build/icon.png and build/icon.ico: the logo on a dark rounded tile with a crimson glow
behind it. electron-builder uses the .ico for Windows and turns the PNG into the .icns macOS needs; a run from the
source tree on Windows names the .ico as its taskbar icon. The mark comes from build/logo.png
(its alpha channel is the shape). Run with any Python that has Pillow:

    server/.venv/Scripts/python.exe apps/desktop/scripts/make-icon.py
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

BUILD = Path(__file__).resolve().parent.parent / "build"
SIZE = 1024
SS = 2  # supersampling for smooth edges
N = SIZE * SS
PAD = round(N * 0.047)  # a little air around the tile, as desktop icons have
RADIUS = round(N * 0.225)
TILE = (12, 12, 12, 255)
BRAND = (254, 69, 65)  # the logo's red
GLOW = (225, 29, 72)  # the crimson accent


def main() -> None:
    tile_mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle((PAD, PAD, N - PAD, N - PAD), radius=RADIUS, fill=255)

    icon = Image.new("RGBA", (N, N), TILE)
    # the glow: a soft crimson ellipse behind the mark, strongest at the centre
    glow = Image.new("L", (N, N), 0)
    ImageDraw.Draw(glow).ellipse((N * 0.14, N * 0.2, N * 0.86, N * 0.8), fill=120)
    glow = glow.filter(ImageFilter.GaussianBlur(N * 0.11))
    icon.paste(Image.new("RGBA", (N, N), (*GLOW, 255)), (0, 0), glow)

    mark = Image.open(BUILD / "logo.png").convert("RGBA").getchannel("A")
    width = round(N * 0.74)
    mark = mark.resize((width, round(mark.height * width / mark.width)), Image.LANCZOS)
    at = ((N - mark.width) // 2, (N - mark.height) // 2)
    # a faint halo of the mark itself, then the mark
    halo = Image.new("L", (N, N), 0)
    halo.paste(mark, at)
    icon.paste(Image.new("RGBA", (N, N), (*BRAND, 255)), (0, 0), halo.filter(ImageFilter.GaussianBlur(N * 0.012)).point(lambda v: v * 0.5))
    icon.paste(Image.new("RGBA", (N, N), (*BRAND, 255)), (0, 0), halo)

    icon.putalpha(ImageChops.multiply(icon.getchannel("A"), tile_mask))
    out = BUILD / "icon.png"
    final = icon.resize((SIZE, SIZE), Image.LANCZOS)
    final.save(out)
    print(out)
    ico = BUILD / "icon.ico"
    final.save(ico, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print(ico)


main()
