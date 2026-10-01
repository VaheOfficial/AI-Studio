"""Draws the app icon (the sidebar logo: a four-point star on a dark rounded square) to build/icon.png.
electron-builder turns that PNG into the .ico / .icns each platform needs. Run with any Python that has Pillow:

    server/.venv/Scripts/python.exe apps/desktop/scripts/make-icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
SS = 2  # supersampling for smooth edges
N = SIZE * SS
UNIT = N / 32  # the logo is drawn on a 32x32 grid
PAD = 1.5 * UNIT  # a little air around the tile, as desktop icons have

STAR = [(16, 5.5), (18.6, 13.4), (26.5, 16), (18.6, 18.6), (16, 26.5), (13.4, 18.6), (5.5, 16), (13.4, 13.4)]
STOPS = [(0.0, (167, 139, 250)), (0.5, (129, 140, 248)), (1.0, (34, 211, 238))]  # the logo's gradient
TILE = (26, 26, 36, 255)


def gradient() -> Image.Image:
    """Top-left to bottom-right, like the SVG's linearGradient."""
    line = Image.new("RGB", (256, 1))
    for x in range(256):
        t = x / 255
        (t0, c0), (t1, c1) = (STOPS[0], STOPS[1]) if t <= 0.5 else (STOPS[1], STOPS[2])
        k = (t - t0) / (t1 - t0)
        line.putpixel((x, 0), tuple(round(a + (b - a) * k) for a, b in zip(c0, c1)))
    # a horizontal ramp stretched over twice the size and rotated 45 degrees gives the diagonal
    ramp = line.resize((N * 2, N * 2)).rotate(-45, resample=Image.BICUBIC)
    left = (ramp.width - N) // 2
    return ramp.crop((left, left, left + N, left + N))


def main() -> None:
    scale = (N - 2 * PAD) / N
    place = lambda v: PAD + v * UNIT * scale  # noqa: E731
    icon = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(icon).rounded_rectangle((PAD, PAD, N - PAD, N - PAD), radius=9 * UNIT * scale, fill=TILE)
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).polygon([(place(x), place(y)) for x, y in STAR], fill=255)
    icon.paste(gradient(), (0, 0), mask)
    out = Path(__file__).resolve().parent.parent / "build" / "icon.png"
    out.parent.mkdir(exist_ok=True)
    icon.resize((SIZE, SIZE), Image.LANCZOS).save(out)
    print(out)


main()
