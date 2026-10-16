#!/usr/bin/env python3
r"""Draws the port's 3DS button icons: `3DS Files/data/buttons3ds.bin`.

The game's text names its buttons with help characters (0x80..0x9d), which
retail draws from BUTTONSOUT, a sheet of the DualShock 2's buttons. On the
3DS those name the wrong keys, so `helpglyph.c` maps each to the 3DS key
that does the same job, and the face buttons, the shoulders and the two
sticks are drawn from this sheet instead. The D-pad, START and SELECT keep
BUTTONSOUT's glyphs, which fit the 3DS as they are.

Nothing here is the disc's: the icons are drawn from shapes, in
BUTTONSOUT's manner -- a dark button lit from the top left, an opaque
body with a softer rim, the symbol in colour -- and in its cell, retail
BUTTONSOUT's 26 x 28 with an advance of 26, so a line of text is as wide
as it was. Each icon is drawn 26 x 23 and set 3 rows down its cell, where
retail's buttons sit in theirs (the face buttons' rows 4..26). The face
buttons' letters are the New 3DS's colours: A red, B yellow, X blue,
Y green.

The sheet is 128 x 128 RGBA8, row 0 at the top, cell i at
((i % 4) * 26, (i / 4) * 28) in HELPGLYPH_3DS_* order (helpglyph.h).

    python tools/buttons3ds_make.py            # writes the .bin
    python tools/buttons3ds_make.py --preview out/buttons3ds.png
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "3DS Files" / "data" / "buttons3ds.bin"

SHEET = 128
CELL_W, CELL_H = 26, 28
ART_H, ART_TOP = 23, 3                   # the icon's rows in its cell
SS = 8                                   # supersampling

ICONS = ["A", "B", "X", "Y", "L", "R", "ZL", "ZR", "CPAD", "CSTICK"]
LETTER_RGB = {
    "A": (232, 64, 52),
    "B": (240, 192, 44),
    "X": (64, 124, 236),
    "Y": (64, 184, 84),
}
WHITE = (236, 236, 236)
RIM_ALPHA = 190                          # BUTTONSOUT's 0xbe edge


# --- letters, as strokes in a unit box (x right, y down) -------------------

def _lines(*pts):
    return [("line", list(pts))]


LETTERS = {
    "A": _lines((0.0, 1.0), (0.5, 0.0), (1.0, 1.0)) + _lines((0.22, 0.66),
                                                           (0.78, 0.66)),
    "X": _lines((0.0, 0.0), (1.0, 1.0)) + _lines((1.0, 0.0), (0.0, 1.0)),
    "Y": _lines((0.0, 0.0), (0.5, 0.5), (1.0, 0.0)) + _lines((0.5, 0.5),
                                                           (0.5, 1.0)),
    "L": _lines((0.0, 0.0), (0.0, 1.0), (1.0, 1.0)),
    "Z": _lines((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)),
    # The bowls: a straight top and bottom joined by a half circle.
    "B": _lines((0.0, 0.0), (0.0, 1.0)) + [
        ("bowl", (0.0, 0.0, 0.5, 0.46)),
        ("bowl", (0.0, 0.46, 0.58, 1.0)),
    ],
    "R": _lines((0.0, 0.0), (0.0, 1.0)) + [
        ("bowl", (0.0, 0.0, 0.56, 0.52)),
    ] + _lines((0.34, 0.52), (1.0, 1.0)),
}
# Width over height, for the letters' boxes.
ASPECT = {"A": 0.86, "B": 0.72, "X": 0.80, "Y": 0.84, "L": 0.62, "R": 0.74,
          "Z": 0.62}


def draw_letter(d, ch, x, y, h, stroke, rgb):
    """Letter `ch` with its box's top left at (x, y), `h` tall, in the
    supersampled space."""
    w = h * ASPECT[ch]
    r = stroke / 2.0
    col = rgb + (255,)

    def P(u, v):
        return (x + u * w, y + v * h)

    def cap(p):
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=col)

    for kind, data in LETTERS[ch]:
        if kind == "line":
            pts = [P(u, v) for u, v in data]
            d.line(pts, fill=col, width=int(round(stroke)))
            for p in pts:
                cap(p)
        else:
            u0, v0, u1, v1 = data
            # The straight part to where the bowl's round part starts, and
            # the round part the right half of an ellipse: as wide as the
            # bowl's straight part leaves, whatever its height.
            rx = 0.5 * (u1 - u0) * w
            xs = x + u1 * w - rx
            top, bot = y + v0 * h, y + v1 * h
            d.line([P(u0, v0), (xs, top)], fill=col, width=int(round(stroke)))
            d.line([P(u0, v1), (xs, bot)], fill=col, width=int(round(stroke)))
            # PIL lays an arc's width inside its box; the lines lie across
            # theirs, so the box grows by half a stroke to meet them.
            box = [xs - rx - r, top - r, xs + rx + r, bot + r]
            d.arc(box, start=-90, end=90, fill=col, width=int(round(stroke)))
            for p in ((xs, top), (xs, bot)):
                cap(p)
    return w


def text_width(s, h, gap):
    return sum(h * ASPECT[c] for c in s) + gap * (len(s) - 1)


def draw_text(d, s, cx, cy, h, stroke, rgb, gap):
    x = cx - text_width(s, h, gap) / 2.0
    y = cy - h / 2.0
    for c in s:
        x += draw_letter(d, c, x, y, h, stroke, rgb) + gap


# --- bodies -----------------------------------------------------------------

def shade(nx, ny):
    """Grey of a body point, lit from the top left; BUTTONSOUT's run from
    0x9f at the lit edge to 0x13 at the far one."""
    v = 0.5 - 0.62 * nx - 0.30 * ny
    v = max(0.0, min(1.0, v))
    return int(0x16 + v * (0x86 - 0x16))


def round_body(img, cx, cy, rad, rim=1.0):
    """A round button: the shaded body with a dark, softer rim."""
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            dx, dy = (x + 0.5 - cx) / rad, (y + 0.5 - cy) / rad
            dd = math.hypot(dx, dy)
            if dd > 1.0:
                continue
            if dd > 1.0 - rim * SS / rad:
                px[x, y] = (0x13, 0x13, 0x13, RIM_ALPHA)
            else:
                g = shade(dx, dy)
                px[x, y] = (g, g, g, 255)


def rect_body(img, x0, y0, x1, y1, rad, frame):
    """A rounded rectangle: a lighter frame `frame` px wide, lit from the
    top left, around a dark shaded face."""
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([x0, y0, x1, y1], radius=rad,
                                        fill=255)
    inner = Image.new("L", img.size, 0)
    ImageDraw.Draw(inner).rounded_rectangle(
        [x0 + frame, y0 + frame, x1 - frame, y1 - frame],
        radius=max(0, rad - frame), fill=255)
    px, mp, ip = img.load(), m.load(), inner.load()
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    hw, hh = (x1 - x0) / 2.0, (y1 - y0) / 2.0
    for y in range(int(y0), int(y1) + 1):
        for x in range(int(x0), int(x1) + 1):
            if not mp[x, y]:
                continue
            nx, ny = (x - cx) / hw, (y - cy) / hh
            if ip[x, y]:
                g = int(shade(nx, ny) * 0.55)
            else:
                g = min(255, shade(nx, ny) + 0x18)
            px[x, y] = (g, g, g, 255)


# --- the icons --------------------------------------------------------------

def icon(name):
    W, H = CELL_W * SS, ART_H * SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = 13.0 * SS, 11.5 * SS
    if name in LETTER_RGB:
        round_body(img, cx, cy, 10.4 * SS)
        draw_text(d, name, cx, cy, 11.5 * SS, 2.7 * SS, LETTER_RGB[name], 0)
    elif name in ("L", "R"):
        # Wider and lower than ZL and ZR, as L1 is beside L2.
        rect_body(img, 1.5 * SS, 4.0 * SS, 24.5 * SS, 19.5 * SS, 3.0 * SS,
                  1.6 * SS)
        draw_text(d, name, cx, 11.75 * SS, 10.0 * SS, 2.4 * SS, WHITE, 0)
    elif name in ("ZL", "ZR"):
        # The cell's full width and taller than L and R, so the two
        # letters can be as bold as L's one: at the size the menus draw
        # them, about 16 x 14, thinner ones ran together (2026-10-16).
        rect_body(img, 0.5 * SS, 1.5 * SS, 25.5 * SS, 21.5 * SS, 3.5 * SS,
                  1.6 * SS)
        draw_text(d, name, cx, cy, 11.5 * SS, 2.2 * SS, WHITE, 1.4 * SS)
    elif name == "CPAD":
        # The Circle Pad: a disc in a round well.
        round_body(img, cx, cy, 10.4 * SS)
        well = Image.new("RGBA", img.size, (0, 0, 0, 0))
        wp = well.load()
        for y in range(H):
            for x in range(W):
                dx, dy = (x + 0.5 - cx) / SS, (y + 0.5 - cy) / SS
                dd = math.hypot(dx, dy)
                if dd <= 8.6:
                    g = 0x1c
                    if dd <= 6.6:
                        g = shade(dx / 6.6, dy / 6.6) + 0x10
                        if 4.6 <= dd <= 5.4:
                            g -= 0x18
                    wp[x, y] = (g, g, g, 255)
        img.alpha_composite(well)
    elif name == "CSTICK":
        # The C-Stick: a small nub on a dark ring.
        rad = 6.6 * SS
        round_body(img, cx, cy, rad, rim=1.0)
        nub = Image.new("RGBA", img.size, (0, 0, 0, 0))
        np_ = nub.load()
        for y in range(H):
            for x in range(W):
                dx, dy = (x + 0.5 - cx) / SS, (y + 0.5 - cy) / SS
                if math.hypot(dx, dy) <= 3.4:
                    g = min(255, shade(dx / 3.4, dy / 3.4) + 0x30)
                    np_[x, y] = (g, g, g, 255)
        img.alpha_composite(nub)
    return img.resize((CELL_W, ART_H), Image.LANCZOS)


def sheet():
    out = Image.new("RGBA", (SHEET, SHEET), (0, 0, 0, 0))
    for i, name in enumerate(ICONS):
        out.paste(icon(name),
                  ((i % 4) * CELL_W, (i // 4) * CELL_H + ART_TOP))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", help="also write a 4x PNG of the sheet")
    a = ap.parse_args()
    s = sheet()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(s.tobytes())
    print("%s: %d bytes, %d icons" % (OUT, SHEET * SHEET * 4, len(ICONS)))
    if a.preview:
        bg = Image.new("RGBA", s.size, (40, 40, 48, 255))
        bg.alpha_composite(s)
        bg.resize((SHEET * 4, SHEET * 4), Image.NEAREST).save(a.preview)


if __name__ == "__main__":
    main()
