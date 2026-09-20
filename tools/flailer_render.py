#!/usr/bin/env python3
r"""Render a Flailer screen to a PNG, the way the game draws it.

`tools/flailer_dump.py` lists what is on a screen; this composites it, so a
screen can actually be looked at without a 3DS. It is the reference the C
renderer (`3DS Files/source/uirender.c`) is written against -- same
geometry, same justification, same fixed-width cells, same PS2 colour scale,
including the two places where the engine does something surprising:

  * `RenderCharacter` (0x0013f698) multiplies a glyph's width by `ScaleX`
    *twice* while scaling its height once and advancing the pen once.
  * `RenderStringFixedWidth` (0x0013fb78) centres each glyph in a cell of
    `Font::FixedWidthCell` and adds the centring term *unscaled* to an
    already-scaled pen.

Both are reproduced rather than corrected, because the screens were laid out
with them on the screen. Pass --fix-scale to see what the pages look like
without the first one.

Usage:
    python tools/flailer_render.py extracted/FRONTEND/FRONTB.BUN 0 -o out.png
    python tools/flailer_render.py extracted/GLOBAL/INGAMEB.BUN --all -o out/
    python tools/flailer_render.py extracted/FRONTEND/FRONTB.BUN 0 \
        --language extracted/LANGUAGES/FE_GERMAN.BIN
"""
import argparse
import os
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flailer_dump as fl                       # noqa: E402
import font_dump as fd                          # noqa: E402
import language_dump as ld                      # noqa: E402
import texture_convert as tc                    # noqa: E402
from bhash import bhash                         # noqa: E402

# IsHelpCharacter (0x0013f9a8) is (u8)(c - 128) < 18; RenderHelpCharacter
# maps each to a BUTTONSOUT glyph through the table at 0x002e8a10.
HELP_FIRST = 0x80
HELP_GLYPH = "abdefgijhknolmcccc"
HELP_FONT_HASH = 0xB85DE386             # bStringHash("BUTTONSOUT")

# Font::FixedWidthCell = GetWidestCharacter(this, this string).
# Back-to-front draw order for the 29 Flailer layers. AddFlailerStrip
# (0x00143990) files each object's strip under LayerRenderInfoTable[Z] and
# RenderLayer (0x00143a68) walks one list; eDisplayFrame calls RenderLayer
# from four loops, all of which count down:
#   0x00112b58  24 -> 20   before the world, with the render targets
#   0x00113680  15 -> 0    the main pass
#   0x001136c0  19 -> 16
#   0x00113708  28 -> 25   last, so 25 ends up frontmost
# The ranges cover 0..28 exactly once, so that is the whole story.
LAYER_ORDER = (
    list(range(24, 19, -1))
    + list(range(15, -1, -1))
    + list(range(19, 15, -1))
    + list(range(28, 24, -1))
)
assert sorted(LAYER_ORDER) == list(range(29))

FIXED_WIDTH_SET = "1234567890:- "

FMT_RIGHT, FMT_LEFT, FMT_CENTER = 0x01, 0x02, 0x04
FMT_DARKBG, FMT_CLIP, FMT_WRAP, FMT_FIXEDWIDTH = 0x08, 0x10, 0x20, 0x40


# -- a tiny RGBA canvas ------------------------------------------------------

class Canvas(object):
    def __init__(self, w, h, background=(16, 16, 24, 255)):
        self.w, self.h = w, h
        self.px = bytearray(bytes(background) * (w * h))

    def blend(self, x, y, r, g, b, a):
        a = int(a)
        if a <= 0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        r, g, b = int(r), int(g), int(b)
        i = (y * self.w + x) * 4
        if a >= 255:
            self.px[i:i + 4] = bytes((r, g, b, 255))
            return
        inv = 255 - a
        self.px[i] = (r * a + self.px[i] * inv) // 255
        self.px[i + 1] = (g * a + self.px[i + 1] * inv) // 255
        self.px[i + 2] = (b * a + self.px[i + 2] * inv) // 255
        self.px[i + 3] = min(255, a + self.px[i + 3] * inv // 255)

    def rect(self, x, y, w, h, color):
        r, g, b, a = color
        for yy in range(int(y), int(y + h)):
            for xx in range(int(x), int(x + w)):
                self.blend(xx, yy, r, g, b, a)

    def write_png(self, path):
        raw = bytearray()
        for y in range(self.h):
            raw.append(0)
            raw += self.px[y * self.w * 4:(y + 1) * self.w * 4]

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">2I5B", self.w, self.h, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
               + chunk(b"IEND", b""))
        Path(path).write_bytes(png)


class Image(object):
    """A decoded texture: RGBA8888, row 0 at the top."""

    def __init__(self, w, h, data):
        self.w, self.h, self.data = w, h, data

    def texel(self, x, y):
        if not (0 <= x < self.w and 0 <= y < self.h):
            return (0, 0, 0, 0)
        i = (y * self.w + x) * 4
        return tuple(self.data[i:i + 4])


def ps2_color(word):
    """0x80 is full intensity on the GS, so double and clamp, as texpack does."""
    return tuple(min(255, ((word >> (8 * i)) & 0xFF) * 2) for i in range(4))


def draw_sprite(canvas, img, sx, sy, sw, sh, dx, dy, dw, dh, tints, alpha):
    """Nearest-neighbour blit of img[sx,sy,sw,sh] into the destination rect.

    `tints` is the four corner colours in strip order (top-left, top-right,
    bottom-right, bottom-left), bilinearly interpolated and multiplied into
    the texel, which is what the GS does with a gouraud colour.
    """
    dw, dh = int(dw), int(dh)
    if dw <= 0 or dh <= 0 or sw <= 0 or sh <= 0:
        return
    tl, tr, br, bl = tints
    for j in range(dh):
        v = (j + 0.5) / dh
        ty = sy + v * sh
        for i in range(dw):
            u = (i + 0.5) / dw
            r, g, b, a = img.texel(int(sx + u * sw), int(ty))
            if a == 0:
                continue
            # bilinear corner tint
            top = [tl[k] + (tr[k] - tl[k]) * u for k in range(4)]
            bot = [bl[k] + (br[k] - bl[k]) * u for k in range(4)]
            t = [top[k] + (bot[k] - top[k]) * v for k in range(4)]
            canvas.blend(int(dx) + i, int(dy) + j,
                         r * t[0] // 255, g * t[1] // 255, b * t[2] // 255,
                         int(a * t[3] / 255 * alpha))


# -- bundle contents ---------------------------------------------------------

class Bundle(object):
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        self.textures = {}          # hash -> Image, decoded on demand
        self._packs = []
        for off, size in tc.find_packs(self.data):
            name, info, blob = tc.parse_pack(self.data, off, size)
            self._packs.append((info, blob))
        self.fonts = {}
        for chunk in fd.find_fonts(self.data):
            f = fd.Font(chunk)
            self.fonts.setdefault(f.hash, f)
            f.fixed_cell = max(
                [f.glyphs[f.by_id[ord(c)]]["advance"]
                 for c in FIXED_WIDTH_SET if ord(c) in f.by_id] or [0.0])

    def texture(self, hash_):
        if hash_ in self.textures:
            return self.textures[hash_]
        img = None
        for info, blob in self._packs:
            for t in tc.textures(info):
                if t["hash"] != hash_:
                    continue
                got = tc.decode(t, blob, level=0)
                if got:
                    img = Image(got[0], got[1], got[2])
                break
            if img:
                break
        self.textures[hash_] = img
        return img


def measure(font, text, scale_x, fixed):
    if not fixed:
        return font.measure(text) * scale_x
    total = 0.0
    for ch in text:
        if ord(ch) in font.by_id:
            total += font.fixed_cell
    return total * scale_x


def render_screen(bundles, screen, lang, fix_scale=False, alpha=1.0):
    canvas = Canvas(screen["res_x"], screen["res_y"])

    def find_texture(h):
        for b in bundles:
            img = b.texture(h)
            if img:
                return img
        return None

    def find_font(h):
        for b in bundles:
            if h in b.fonts:
                return b.fonts[h]
        return None

    missing = {"texture": 0, "font": 0, "string": 0}

    # Z is a layer index, and eDisplayFrame walks the layers in the fixed,
    # mostly descending order in LAYER_ORDER. Within one layer the file order
    # is the draw order, because AddFlailerStrip appends to the tail of
    # LayerRenderInfoTable[Z].
    for layer in LAYER_ORDER:
        for o in screen["objects"]:
            if o["z"] != layer or o["visible"] != 1:
                continue
            if o["kind"] == "bitmap":
                img = find_texture(o["texture_hash"])
                if not img:
                    missing["texture"] += 1
                    continue
                # RenderSingleFlailerBitmap truncates both to ints.
                w = int(img.w * o["scale_x"])
                h = int(img.h * o["scale_y"])
                uv = o["uv"]
                us = [uv[0], uv[2], uv[4], uv[6]]
                vs = [uv[1], uv[3], uv[5], uv[7]]
                sx, sy = min(us) * img.w, min(vs) * img.h
                sw, sh = (max(us) - min(us)) * img.w, (max(vs) - min(vs)) * img.h
                tints = [ps2_color(c) for c in o["gourad"]]
                draw_sprite(canvas, img, sx, sy, sw, sh,
                            o["top_left_x"], o["top_left_y"], w, h,
                            tints, alpha)
                continue

            font = find_font(o["font_hash"])
            if not font:
                missing["font"] += 1
                continue
            text = o["string"]
            if o["language_id"] and lang:
                got = lang.by_id.get(o["language_id"])
                if got is None:
                    missing["string"] += 1
                else:
                    text = got
            if not text:
                continue

            fixed = bool(o["format_options"] & FMT_FIXEDWIDTH)
            width = measure(font, text, o["scale_x"], fixed)
            pen = o["top_left_x"]
            if o["format_options"] & FMT_RIGHT:
                pen -= width
            elif o["format_options"] & FMT_CENTER:
                pen -= width * 0.5
            if o["format_options"] & FMT_DARKBG:
                canvas.rect(pen, o["top_left_y"], width,
                            font.height * o["scale_y"], (0, 0, 0, 160))

            color = ps2_color(o["color"])
            sheet = find_texture(o["font_hash"])
            prev = None
            for ch in text:
                c = ord(ch)
                if HELP_FIRST <= c < HELP_FIRST + len(HELP_GLYPH):
                    hf = find_font(HELP_FONT_HASH)
                    hs = find_texture(HELP_FONT_HASH)
                    gid = ord(HELP_GLYPH[c - HELP_FIRST])
                    if hf and hs and gid in hf.by_id:
                        g = hf.glyphs[hf.by_id[gid]]
                        draw_sprite(canvas, hs, g["x"], g["y"], g["width"],
                                    g["height"], pen,
                                    o["top_left_y"] + g["offset"] * o["scale_y"],
                                    g["width"] * o["scale_x"],
                                    g["height"] * o["scale_y"],
                                    [color] * 4, alpha)
                        pen += g["advance"] * o["scale_x"]
                    prev = None
                    continue
                if c not in font.by_id or not sheet:
                    prev = None
                    continue
                g = font.glyphs[font.by_id[c]]
                if fixed:
                    inset = (font.fixed_cell - g["advance"]) * 0.5
                    draw_sprite(canvas, sheet, g["x"], g["y"], g["width"],
                                g["height"], pen + inset,
                                o["top_left_y"] + g["offset"] * o["scale_y"],
                                g["width"] * o["scale_x"],
                                g["height"] * o["scale_y"], [color] * 4, alpha)
                    pen += font.fixed_cell * o["scale_x"]
                    prev = None
                    continue
                if prev is not None:
                    pen += font.kerning(prev, c) * o["scale_x"]
                gw = g["width"] * o["scale_x"]
                if not fix_scale:
                    gw *= o["scale_x"]       # the 0x0013f794 double multiply
                draw_sprite(canvas, sheet, g["x"], g["y"], g["width"],
                            g["height"], pen,
                            o["top_left_y"] + g["offset"] * o["scale_y"],
                            gw, g["height"] * o["scale_y"], [color] * 4, alpha)
                pen += g["advance"] * o["scale_x"]
                prev = c
    return canvas, missing


# The menu system's effect on a screen, so a render can show what the player
# actually sees rather than the authored colours. FlailerMenu discovers text
# objects called MENUITEM_0..15 and recolours them through
# SetColor__16FlailerTextChunk, which replaces the low 24 bits and keeps the
# chunk's alpha -- docs/formats/flailer-menu.md. The colour constants are the
# shipped values of HighlightR/G/B and GrayedR/G/B.
HIGHLIGHT_RGB = 128 | (64 << 8) | (0 << 16)
GRAYED_RGB = 24 | (24 << 8) | (24 << 16)


def apply_menu(screen, highlight=None, grayed=()):
    """Recolour MENUITEM_n objects in place, as FlailerMenu would."""
    wanted = {}
    for n in range(16):
        wanted[bhash("MENUITEM_%d" % n)] = n
    touched = []
    for o in screen["objects"]:
        n = wanted.get(o["name_hash"])
        if n is None or o["object_type"] != 1:
            continue
        rgb = None
        if n in grayed:
            rgb = GRAYED_RGB
        elif n == highlight:
            rgb = HIGHLIGHT_RGB
        if rgb is not None:
            o["color"] = (o["color"] & 0xFF000000) | (rgb & 0x00FFFFFF)
        touched.append(n)
    return sorted(touched)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="the .BUN holding the screen")
    ap.add_argument("index", nargs="?", type=int, default=0)
    ap.add_argument("--all", action="store_true", help="render every screen")
    ap.add_argument("--also", action="append", default=[],
                    help="another bundle to resolve hashes against (repeatable)")
    ap.add_argument("--language", help=r"LANGUAGES\FE_*.BIN")
    ap.add_argument("--fix-scale", action="store_true",
                    help="drop the engine's duplicate ScaleX on glyph width")
    ap.add_argument("--menu-item", type=int, default=None,
                    metavar="N",
                    help="highlight MENUITEM_N as the menu system would")
    ap.add_argument("--gray", type=int, action="append", default=[],
                    metavar="N", help="gray MENUITEM_N out (repeatable)")
    ap.add_argument("-o", "--out", default="screen.png",
                    help="a .png, or a directory with --all")
    args = ap.parse_args()

    bundles = [Bundle(args.file)] + [Bundle(p) for p in args.also]
    data = bundles[0].data
    found = fl.find_flailers(data)
    if not found:
        sys.exit("no Flailer chunk in %s" % args.file)
    off, size = found[0]
    screens = fl.parse(data, off, size)["screens"]

    lang = ld.load(args.language) if args.language else None

    todo = range(len(screens)) if args.all else [args.index]
    if args.all:
        os.makedirs(args.out, exist_ok=True)
    for i in todo:
        if not 0 <= i < len(screens):
            sys.exit("screen %d out of range (%d screens)" % (i, len(screens)))
        s = screens[i]
        if args.menu_item is not None or args.gray:
            apply_menu(s, args.menu_item, set(args.gray))
        canvas, missing = render_screen(bundles, s, lang, args.fix_scale)
        out = (os.path.join(args.out, "screen%02d_%08x.png" % (i, s["name_hash"]))
               if args.all else args.out)
        canvas.write_png(out)
        print("%s  screen %d hash %08x  %d objects%s"
              % (out, i, s["name_hash"], len(s["objects"]),
                 "" if not any(missing.values())
                 else "  missing " + ", ".join("%d %s" % (v, k)
                                               for k, v in missing.items() if v)))


if __name__ == "__main__":
    main()
