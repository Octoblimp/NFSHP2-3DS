#!/usr/bin/env python3
"""Cross-check 3DS Files/source/flailer.c, the Flailer runtime, against the
retail image, SLES_507.31.

**The model** is retail's own: LoaderFlailerChunk (0x0013fba0) run on the
Flailer chunks of GLOBALB, FRONTB and INGAMEB -- INGAMEB twice, so that
every one of its screens is found in two projects and FindFlailerScreen's
order decides which -- then FindFlailerScreen, FindFlailerObject,
FindFlailerObjectByGroup, the object, text and bitmap methods and the
Flailer* wrappers, all run in retail_model.RetailEmu on those bytes, with
retail's bStrCmp, bStrLen and bVSPrintf. The harness
(tools/src/flailer_test.c) runs flailer.c over bui.c on the same files.

**The stubs** are what the renderer answers for on the port: the text's
GetScaledWidth and GetScaledHeight, and the bitmap's GetTextureInfo, whose
Width and Height everything a bitmap measures is made from. Both sides
answer from the object alone: a text object is (strlen * 9 + NameHash % 7)
* ScaleX wide and (NameHash % 23 + 8) * ScaleY high, and a bitmap's
texture TextureHash % 509 + 1 by TextureHash % 251 + 1. The model's
TextureInfo is a scratch one; the cache word, pTextureInfo, is left as it
was, as the port leaves it.

**Compared** are what each call returns, the bytes of the object it
touched (all but the bTNode and pFlailerStrip, and a text object's
characters up to the NUL), the order of the project list and of each
project's screens, and now and then a CRC of every object and screen.

**The script** finds screens near and far through the lists, then runs
every method over every object on the HUD's screen and a sample of the
rest -- texts of each alignment, bitmaps, names that two objects share --
with values that change something, values that do not, -0, fractions,
truncation both ways; then the wrappers by
hash, including screens and objects that are not there, and the groups.

    python tools/flailer_check.py
    python tools/flailer_check.py --mutate [--only a,b]
    python tools/flailer_check.py --dump out/flailer
"""
import argparse
import ctypes
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/flailer_test.c"
FLAILER = "3DS Files/source/flailer.c"
SOURCES = [HARNESS, FLAILER, "3DS Files/source/bprintf.c",
           "3DS Files/source/bui.c", "3DS Files/source/bchunk.c"]
HARNESS_TIMEOUT = 60

SD = Path(os.environ.get("APPDATA", "")) / "Azahar" / "sdmc" / "NFSHP2"
LOADS = ["GLOBAL/GLOBALB.BUN", "FRONTEND/FRONTB.BUN", "GLOBAL/INGAMEB.BUN",
         "GLOBAL/INGAMEB.BUN"]

GP = retail_model.RETAIL_GP
PROJ_HEAD = GP - 22424

F_LOADER = 0x0013fba0
F_SCREEN = 0x00140378
F_OBJECT = 0x00143d50
F_GROUP = 0x00143dd8
S_TEXT_W = 0x00140d30
S_TEXT_H = 0x00140cd8
S_TEXINFO = 0x00141368

# name: (address, argument kinds). o the object, i an int, f a float, s a
# string, v a bVector4, p a float or q an int out-pointer pair, b four int
# out-pointers; the result is I an int, F a float, P, Q or B what the
# pointers were given, or nothing.
METHODS = {
    "get_alpha": (0x00140518, "o", "I"),
    "set_z": (0x00140568, "oi", ""),
    "get_width": (0x00140588, "o", "I"),
    "get_height": (0x001405e0, "o", "I"),
    "get_width_float": (0x00140638, "o", "F"),
    "get_height_float": (0x00140688, "o", "F"),
    "set_alpha": (0x001406d8, "oi", ""),
    "set_rotation": (0x00140708, "of", ""),
    "set_visibility": (0x00140728, "oi", ""),
    "set_color": (0x00140740, "ov", ""),
    "set_scale_x": (0x001407d0, "of", ""),
    "set_scale_y": (0x001407f8, "of", ""),
    "get_center": (0x00140850, "op", "P"),
    "set_center_x": (0x001408e8, "of", ""),
    "set_center_y": (0x00140930, "of", ""),
    "get_top_left": (0x00140978, "op", "P"),
    "set_top_left_x": (0x00140a20, "of", ""),
    "set_top_left_y": (0x00140a48, "of", ""),
    "set_clip_to_poly": (0x00140a70, "oi", ""),
    "delete_strip": (0x00140b78, "o", ""),
    "t_set_format": (0x00140c68, "oi", ""),
    "t_clear_format": (0x00140c80, "oi", ""),
    "t_set_color": (0x00140ca0, "oi", ""),
    "t_set_string": (0x00140e20, "os", ""),
    "t_update_language": (0x00140e98, "o", ""),
    "t_set_language": (0x00140ea8, "oi", ""),
    "t_set_alpha": (0x00140ed0, "oi", ""),
    "t_get_alpha": (0x00140f08, "o", "I"),
    "t_set_color_vector": (0x00140f10, "ov", ""),
    "b_set_alpha": (0x001411d8, "oii", ""),
    "b_set_rotation": (0x00141258, "of", ""),
    "b_set_color": (0x00141288, "oi", ""),
    "b_set_color_vector": (0x001412b0, "ov", ""),
    "b_change_texture": (0x00141350, "oi", ""),
    "b_get_alpha": (0x001413e8, "oi", "I"),
    "printf_chunk": (0x00143f08, "osi", "I"),
    "set_width": (0x00140770, "of", ""),
    "set_height": (0x001407a0, "of", ""),
    "scale_about_center": (0x00140820, "of", ""),
}

# The same, by (screen, object) hash: h is the pair.
WRAPPERS = {
    "printf_d": (0x00143e70, "hsi", "I"),
    "printf_s": (0x00143e70, "hss", "I"),
    "printf_dd": (0x00143e70, "hsii", "I"),
    "set_text_color": (0x00143f88, "hi", ""),
    "set_text_format": (0x00143ff0, "hi", ""),
    "clear_text_format": (0x00144030, "hi", ""),
    "get_top_left": (0x00144070, "hp", "P"),
    "get_top_left_int": (0x001440d8, "hq", "Q"),
    "get_top_left_x": (0x00144140, "h", "F"),
    "get_top_left_y": (0x00144168, "h", "F"),
    "get_width": (0x00144190, "h", "I"),
    "get_height": (0x001441c8, "h", "I"),
    "set_top_left": (0x00144398, "hii", ""),
    "set_z": (0x00144418, "hi", ""),
    "set_top_left_y": (0x00144458, "hi", ""),
    "set_top_left_x": (0x001444a0, "hi", ""),
    "get_scale": (0x001444e8, "hp", "P"),
    "set_scale_x": (0x00144530, "hf", ""),
    "set_scale_y": (0x00144570, "hf", ""),
    "set_center": (0x001445f0, "hii", ""),
    "get_alpha": (0x001448b0, "h", "I"),
    "set_alpha": (0x001448e8, "hi", ""),
    "set_rotation": (0x00144928, "hf", ""),
    "set_visibility": (0x00144968, "hi", ""),
    "set_language": (0x001449a8, "hi", ""),
    "set_object_color": (0x001449e8, "hv", ""),
    "change_texture": (0x00144a28, "hi", ""),
    "set_group_visibility": (0x001454e8, "hi", ""),
    "set_width": (0x00144200, "hf", ""),
    "set_height": (0x00144240, "hf", ""),
    "get_bounding_box": (0x00144280, "hb", "B"),
    "set_clip_to_poly": (0x00144358, "hi", ""),
    "scale_about_center": (0x001445b0, "hf", ""),
    "set_center_y": (0x001446e0, "hi", ""),
    "set_center_x": (0x00144760, "hi", ""),
    "get_center": (0x001447e0, "hq", "Q"),
    "get_center_y": (0x00144860, "h", "I"),
    "get_center_x": (0x00144888, "h", "I"),
    "set_group_position": (0x00145308, "hiff", ""),
    "offset_group": (0x001453d0, "hii", ""),
    "set_group_render_on_poly": (0x00145488, "hi", ""),
    "set_group_alpha": (0x00145560, "hi", ""),
    "make_vertical_line_f": (0x001455e8, "hff", ""),
    "make_vertical_line": (0x00145690, "hii", ""),
}


def fbits(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def bitsf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


def f32(v):
    return ctypes.c_float(v).value


def chunks(d, off, end):
    while off + 8 <= end:
        t, n = struct.unpack_from("<II", d, off)
        yield t, n, off + 8
        off += 8 + n


def flailer_chunk(data):
    for t, n, p in chunks(data, 0, len(data)):
        if t == 0x80010200:
            return p - 8, n
    raise SystemExit("no Flailer chunk")


def walk(mem, base, size):
    """bui's view of the chunk at `base`: the project payload, the screen
    containers (def payload or None, [(object payload, size)])."""
    proj = None
    screens = []
    for t, n, p in chunks(mem, base + 8, base + 8 + size):
        if t == 0x10213:
            proj = p
        elif t == 0x80010201:
            sdef, objs = None, []
            for t2, n2, p2 in chunks(mem, p, p + n):
                if t2 == 0 and n2 == 0:
                    raise SystemExit("padding inside a screen: bui skips it, "
                                     "the loader links it")
                if t2 == 0x10203:
                    sdef = p2
                else:
                    objs.append((p2, n2))
            screens.append((sdef, objs))
    return proj, screens


class Project(object):
    def __init__(self, n, mem, base, size):
        self.n = n
        self.proj, self.screens = walk(mem, base, size)
        self.objects = [o for _, objs in self.screens for o in objs]


# ================================================================== script

def bhash(s):
    h = 0xffffffff
    for c in s.encode("latin-1"):
        h = (h * 33 + c) & M32
    return h


HUD = 0xf1f1f8e5
MISSING = 0x12345678

FLOATS = [0.0, -0.0, 1.0, 0.5, -0.5, 320.25, -17.75, 1.0e6, 2.9999998,
          -2.9999998, 255.9, 128.0, 3.0e9, -3.0e9]


def fl(v):
    return "%#x" % fbits(v)


def survey():
    """Each file's screens: (hash, [(name, group, type, format, size)])."""
    out = []
    for rel in LOADS[:3]:
        d = (SD / rel).read_bytes()
        base, size = flailer_chunk(d)
        _, screens = walk(d, base, size)
        rows = []
        for sdef, objs in screens:
            h = struct.unpack_from("<I", d, sdef + 8)[0] if sdef else None
            ol = []
            for p, n in objs:
                nh, gh = struct.unpack_from("<II", d, p + 8)
                ty = d[p + 40]
                fmt = struct.unpack_from("<I", d, p + 88)[0] if ty == 1 else 0
                ol.append((nh, gh, ty, fmt, n))
            rows.append((h, ol))
        out.append(rows)
    return out


def battery(kind, n):
    """Method calls for an object of type `kind`; `n` varies them."""
    f = FLOATS
    s = []
    s += ["m|get_alpha", "m|get_width", "m|get_height",
          "m|get_width_float", "m|get_height_float", "m|get_top_left",
          "m|get_center"]
    s += ["m|set_z|%d" % (n % 29), "m|set_z|%d" % (n % 29),
          "m|set_z|%d" % (300 + n)]
    s += ["m|set_scale_x|%s" % fl(f[n % len(f)]),
          "m|set_scale_y|%s" % fl(f[(n + 3) % len(f)]),
          "m|set_scale_x|%s" % fl(-0.0), "m|set_scale_x|%s" % fl(0.0),
          "m|set_scale_x|%s" % fl(1.5), "m|set_scale_y|%s" % fl(0.75)]
    s += ["m|get_top_left", "m|get_center", "m|get_width", "m|get_height"]
    s += ["m|set_top_left_x|%s" % fl(f[(n + 5) % len(f)]),
          "m|set_top_left_y|%s" % fl(f[(n + 6) % len(f)]),
          "m|set_top_left_x|%s" % fl(f[(n + 5) % len(f)]),
          "m|set_center_x|%s" % fl(100.5 + n),
          "m|set_center_y|%s" % fl(-40.25 + n), "m|get_top_left",
          "m|get_center"]
    s += ["m|set_alpha|%d" % (n * 37 % 256), "m|get_alpha",
          "m|set_alpha|%d" % (n * 37 % 256), "m|set_alpha|0x1ff",
          "m|get_alpha"]
    s += ["m|set_rotation|%s" % fl(f[(n + 7) % len(f)]),
          "m|set_rotation|%s" % fl(45.9), "m|set_rotation|%s" % fl(-45.9),
          "m|set_rotation|%s" % fl(45.1)]
    s += ["m|set_visibility|1", "m|set_visibility|0", "m|set_visibility|3",
          "m|set_visibility|0x100", "m|delete_strip"]
    s += ["m|set_color|%s|%s|%s|%s" % (fl(10.9), fl(200.2), fl(-1.5),
                                       fl(64.0)),
          "m|set_color|%s|%s|%s|%s" % (fl(10.9), fl(200.2), fl(-1.5),
                                       fl(64.0)),
          "m|set_color|%s|%s|%s|%s" % (fl(300.0), fl(0.0), fl(128.0),
                                       fl(-3.0))]
    s += ["m|set_clip_to_poly|%#x" % (0x5000 + n),
          "m|set_clip_to_poly|%#x" % (0x5000 + n),
          "m|set_clip_to_poly|0xffffffff"]
    # A value that is already there, after another setter has stamped
    # DirtyFlag: the "same" tests are what keep the stamp.
    z = "m|set_z|%d" % (300 + n)
    s += ["m|set_top_left_x|%s" % fl(64.5 + n), z,
          "m|set_top_left_x|%s" % fl(64.5 + n),
          "m|set_top_left_y|%s" % fl(-8.0 - n), z,
          "m|set_top_left_y|%s" % fl(-8.0 - n),
          "m|set_scale_y|%s" % fl(2.0), z, "m|set_scale_y|%s" % fl(2.0),
          "m|set_clip_to_poly|%#x" % (0x6000 + n), z,
          "m|set_clip_to_poly|%#x" % (0x6000 + n)]
    if kind == 1:
        s += ["m|t_get_alpha", "m|t_set_alpha|0x40", "m|t_set_alpha|0x40",
              "m|t_set_alpha|-1", "m|t_get_alpha",
              "m|t_set_color|0x123456", "m|t_set_color|0xff123456",
              "m|t_set_color|0x00654321",
              "m|t_set_color_vector|%s|%s|%s|%s" % (fl(1.0), fl(2.0),
                                                    fl(3.0), fl(4.0)),
              "m|t_set_format|4", "m|get_top_left", "m|get_center",
              "m|t_set_format|1", "m|get_top_left",
              "m|t_clear_format|4", "m|get_top_left",
              "m|t_clear_format|0xffffffff", "m|get_top_left",
              "m|t_set_format|%#x" % (n & 0x7f),
              "m|t_set_string|SPEED %d" % n,
              "m|t_set_string|SPEED %d" % n, "m|get_width",
              "m|t_set_string|", "m|get_width",
              "m|t_set_string|%s" % ("Z" * (n % 40 + 1)), "m|get_width",
              "m|t_set_language|%#x" % (0x1000 + n),
              "m|t_set_language|%#x" % (0x1000 + n),
              "m|t_update_language", "m|t_set_language|0",
              "m|t_set_string|after", "m|get_top_left",
              "m|printf_chunk|%%03d km/h|%d" % (n * 7),
              "m|printf_chunk|%%d|%d" % -n,
              "m|t_set_string|LAP %d" % n, z, "m|t_set_string|LAP %d" % n,
              "m|t_set_language|%#x" % (0x2000 + n), z,
              "m|t_set_language|%#x" % (0x2000 + n),
              "m|t_set_color|0x0a0b0c", z, "m|t_set_color|0x0a0b0c",
              "m|t_set_alpha|0x21", z, "m|t_set_alpha|0x21"]
    if kind == 2:
        s += ["m|b_get_alpha|0", "m|b_get_alpha|3",
              "m|b_set_alpha|0x22|-1", "m|b_set_alpha|0x33|2",
              "m|b_set_alpha|0x44|1", "m|b_set_alpha|0x155|0",
              "m|b_get_alpha|2", "m|b_get_alpha|0",
              "m|b_set_rotation|%s" % fl(12.7),
              "m|b_set_rotation|%s" % fl(12.2),
              "m|b_set_rotation|%s" % fl(-0.9),
              "m|b_set_color|0x80808080", "m|b_set_color|0x80808080",
              "m|b_set_color|0x10203040",
              "m|b_set_color_vector|%s|%s|%s|%s" % (fl(5.5), fl(6.5),
                                                    fl(7.5), fl(8.5)),
              "m|b_change_texture|%#x" % (0xabc000 + n),
              "m|b_change_texture|%#x" % (0xabc000 + n), "m|get_width",
              "m|get_height",
              # Corner 0 is the only one SetColor asks.
              "m|b_set_color|0x40302010", "m|b_set_alpha|0x11|3",
              "m|b_set_color|0x40302010", "m|b_set_alpha|0x12|0",
              "m|b_set_color|0x12302010", "m|b_set_rotation|%s" % fl(3.0),
              "m|b_set_color|0x12302010",
              # The TextureInfo GetTextureInfo caches, which ChangeTexture
              # lets go.
              "poke|84|%#x" % (0x00500000 + n * 16),
              "m|b_change_texture|%#x" % (0xabc000 + n),
              "poke|84|%#x" % (0x00500000 + n * 16),
              "m|b_change_texture|%#x" % (0xabd000 + n)]
    return s


def battery2(kind, n):
    """SetWidth, SetHeight and ScaleAboutCenter, from a scale that is not
    0: the half sizes are divided by it."""
    s = ["m|set_scale_x|%s" % fl(1.25), "m|set_scale_y|%s" % fl(0.5),
         "m|scale_about_center|%s" % fl(2.0), "m|get_top_left",
         "m|scale_about_center|%s" % fl(2.0),
         "m|scale_about_center|%s" % fl(0.5 + (n % 5) * 0.25),
         "m|set_width|%s" % fl(37.0 + n), "m|set_height|%s" % fl(19.5),
         "m|set_width|%s" % fl(37.0 + n), "m|get_width_float",
         "m|get_height_float", "m|set_z|%d" % (300 + n),
         "m|set_height|%s" % fl(23.25), "m|set_z|%d" % (300 + n),
         "m|set_height|%s" % fl(23.25)]
    if kind == 1:
        # Each alignment, and none: LEFT first, then CENTER, then RIGHT.
        for f in (0, 2, 4, 1, 5, 3, 7):
            s += ["m|t_clear_format|7", "m|t_set_format|%d" % f,
                  "m|scale_about_center|%s" % fl(1.0 + f * 0.375),
                  "m|get_top_left"]
    return s


def script():
    sv = survey()
    s = ["load|%s" % (SD / rel) for rel in LOADS]
    s += ["order", "state"]

    # Screens near and far: a find past two moves the screen and its
    # project to the front; a near one does not.
    ing = sv[2]
    fe = sv[1]
    glob = sv[0]
    for h in (glob[0][0], glob[1][0], glob[2][0], HUD, HUD, fe[30][0],
              ing[0][0], glob[0][0], 0x0ce3f7ce, 0xfa2ac5c6, MISSING,
              ing[34][0], fe[0][0], fe[1][0], HUD):
        s += ["screen|%#x" % h, "order"]

    # Every object on the HUD's screen, by name and type.
    hud = [r for r in ing if r[0] == HUD][0][1]
    n = 0
    for nh, gh, ty, fmt, size in hud:
        for t in (0, ty, 3 - ty):
            s.append("find|%#x|%#x|%d" % (HUD, nh, t))
        s.append("find|%#x|%#x|%d" % (HUD, nh, ty))
        s += battery(ty, n)
        s += battery2(ty, n)
        n += 1
    s += ["state", "order"]

    # A sample of the rest: every seventh object of every screen.
    for rows in sv:
        for h, objs in rows:
            for k, (nh, gh, ty, fmt, size) in enumerate(objs):
                if k % 7:
                    continue
                s.append("find|%#x|%#x|%d" % (h, nh, ty))
                s += battery(ty, n)[::3]
                s += battery2(ty, n)
                n += 1
    s += ["state", "order"]

    # Names two objects on one screen share: the type picks.
    for rows in sv:
        for h, objs in rows:
            seen = {}
            for nh, gh, ty, fmt, size in objs:
                seen.setdefault(nh, []).append(ty)
            for nh, tys in seen.items():
                if len(tys) > 1:
                    for t in (0, 1, 2):
                        s += ["find|%#x|%#x|%d" % (h, nh, t), "m|get_alpha"]

    # Groups: walk each from the head and on, by type.
    for rows in sv:
        for h, objs in rows:
            groups = []
            for nh, gh, ty, fmt, size in objs:
                if gh != 0xffffffff and gh not in groups:
                    groups.append(gh)
            for gh in groups[:4]:
                for t in (0, 1, 2):
                    s.append("group|%#x|%#x|%d|0" % (h, gh, t))
                    for _ in range(4):
                        s.append("group|%#x|%#x|%d|1" % (h, gh, t))
    s += ["group|%#x|%#x|0|0" % (MISSING, 0x1)]

    # The wrappers, on objects there and not.
    targets = []
    for nh, gh, ty, fmt, size in hud[::5]:
        targets.append((HUD, nh))
    targets += [(HUD, MISSING), (MISSING, hud[0][0]), (fe[3][0],
                                                       fe[3][1][0][0]),
                (glob[1][0], glob[1][1][0][0])]
    for k, (h, nh) in enumerate(targets):
        w = "%#x|%#x" % (h, nh)
        s += ["w|get_top_left|" + w, "w|get_top_left_int|" + w,
              "w|get_top_left_x|" + w, "w|get_top_left_y|" + w,
              "w|get_width|" + w, "w|get_height|" + w, "w|get_scale|" + w,
              "w|get_alpha|" + w]
        s += ["w|printf_d|%s|%%d|%d" % (w, k * 13 - 50),
              "w|printf_s|%s|[%%s]|lap" % w,
              "w|printf_dd|%s|%%d/%%d|%d|%d" % (w, k % 4, 3),
              "w|printf_d|%s|%%02d|%d" % (w, k % 4),
              "w|set_text_color|%s|%#x" % (w, 0x00808080 + k),
              "w|set_text_format|%s|4" % w, "w|get_top_left|" + w,
              "w|clear_text_format|%s|5" % w, "w|get_top_left|" + w,
              "w|set_top_left|%s|%d|%d" % (w, 100 + k, -20 - k),
              "w|set_top_left|%s|%d|%d" % (w, 100 + k, -20 - k),
              "w|set_top_left_x|%s|%d" % (w, 16777217 + k),
              "w|set_top_left_y|%s|%d" % (w, -7),
              "w|set_z|%s|%d" % (w, k % 29),
              "w|set_scale_x|%s|%s" % (w, fl(1.25)),
              "w|set_scale_y|%s|%s" % (w, fl(0.8)),
              "w|set_center|%s|%d|%d" % (w, 320, 240),
              "w|get_top_left|" + w, "w|get_top_left_int|" + w,
              "w|set_alpha|%s|%d" % (w, k * 11 % 256),
              "w|get_alpha|" + w,
              "w|set_rotation|%s|%s" % (w, fl(30.5 + k)),
              "w|set_visibility|%s|0" % w, "w|set_visibility|%s|1" % w,
              "w|set_language|%s|%#x" % (w, 0x777 + k),
              "w|set_object_color|%s|%s|%s|%s|%s" % (w, fl(1.0), fl(2.0),
                                                     fl(3.0), fl(4.0)),
              "w|change_texture|%s|%#x" % (w, 0x1234 + k)]
        s += ["w|set_width|%s|%s" % (w, fl(48.0 + k)),
              "w|set_height|%s|%s" % (w, fl(12.5)),
              "w|get_bounding_box|" + w,
              "w|set_clip_to_poly|%s|%#x" % (w, 0x7000 + k),
              "w|set_clip_to_poly|%s|%#x" % (w, 0x7000 + k),
              "w|scale_about_center|%s|%s" % (w, fl(1.5)),
              "w|set_center_y|%s|%d" % (w, 200 + k),
              "w|set_center_x|%s|%d" % (w, 300 - k),
              "w|get_bounding_box|" + w,
              "w|make_vertical_line_f|%s|%s|%s" % (w, fl(100.0),
                                                   fl(40.0 + k)),
              "w|make_vertical_line_f|%s|%s|%s" % (w, fl(-2.5),
                                                   fl(60.25)),
              "w|make_vertical_line|%s|%#x|%#x" % (w, hud[1][0],
                                                   hud[2 + k % 7][0]),
              "w|make_vertical_line|%s|%#x|%#x" % (w, MISSING, hud[2][0]),
              "w|make_vertical_line|%s|%#x|%#x" % (w, hud[1][0], MISSING)]
        # The PS2 hands back its stack for an object that is not there.
        if h != MISSING and nh != MISSING:
            s += ["w|get_center|" + w, "w|get_center_y|" + w,
                  "w|get_center_x|" + w]
    s += ["state"]
    for rows in sv:
        for h, objs in rows[:6]:
            groups = sorted({gh for _, gh, _, _, _ in objs
                             if gh != 0xffffffff})
            for gh in groups[:3]:
                s += ["w|set_group_visibility|%#x|%#x|0" % (h, gh), "state",
                      "w|set_group_visibility|%#x|%#x|2" % (h, gh)]
                anchor = [nh for nh, g, _, _, _ in objs if g == gh][0]
                s += ["w|set_group_position|%#x|%#x|%#x|%s|%s"
                      % (h, gh, anchor, fl(10.5), fl(-20.0)), "state",
                      "w|offset_group|%#x|%#x|%d|%d" % (h, gh, 3, -5),
                      "state",
                      "w|set_group_render_on_poly|%#x|%#x|%#x"
                      % (h, gh, 0x99 + gh % 5), "state",
                      "w|set_group_alpha|%#x|%#x|%d" % (h, gh, 0x30),
                      "state"]
            if groups:
                s += ["w|set_group_position|%#x|%#x|%#x|%s|%s"
                      % (h, groups[0], MISSING, fl(1.0), fl(1.0))]
    s += ["w|set_group_visibility|%#x|1|1" % MISSING, "state", "order"]
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        e.put32(PROJ_HEAD, PROJ_HEAD)
        e.put32(PROJ_HEAD + 4, PROJ_HEAD)
        e.stub(S_TEXT_W, self.text_w)
        e.stub(S_TEXT_H, self.text_h)
        e.stub(S_TEXINFO, self.texinfo)
        self.projects = []
        self.obj_at = {}
        self.screen_at = {}
        self.proj_at = {}
        self.cur = 0
        self.scratch = e.alloc(4096)

    def emit(self, s):
        self.out.append(s)

    # ---- stubs

    def ret_f(self, em, v):
        em.fpr[0] = fbits(f32(v))

    def text_len(self, o):
        e = self.e
        mx = s32(e.u32(o + 84))
        n = 0
        while n < mx and e.mem[o + 100 + n]:
            n += 1
        return n

    def text_w(self, em):
        o = em.reg[4] & M32
        k = self.text_len(o) * 9 + self.e.u32(o + 8) % 7
        self.ret_f(em, bitsf(self.e.u32(o + 56)) * float(k))

    def text_h(self, em):
        o = em.reg[4] & M32
        k = self.e.u32(o + 8) % 23 + 8
        self.ret_f(em, bitsf(self.e.u32(o + 60)) * float(k))

    def texinfo(self, em):
        o = em.reg[4] & M32
        h = self.e.u32(o + 80)
        a = self.scratch + 3072
        self.e.write(a + 36, struct.pack("<hh", h % 509 + 1, h % 251 + 1))
        return a

    # ---- output

    def name(self, a):
        if a == 0:
            return "none"
        return self.obj_at.get(a, "stray")

    def dump(self, what, a):
        e = self.e
        if a == 0 or a not in self.obj_at:
            self.emit("  %s -" % what)
            return
        size = self.size_of[a]
        mem = e.mem
        line = "  %s %s %s " % (what, self.obj_at[a],
                                bytes(mem[a + 8:a + 44]).hex())
        if mem[a + 40] == 1 and size >= 100:
            n = self.text_len(a)
            line += '%s "%s"' % (bytes(mem[a + 48:a + 100]).hex(),
                                 bytes(mem[a + 100:a + 100 + n])
                                 .decode("latin-1"))
        else:
            line += bytes(mem[a + 48:a + size]).hex()
        self.emit(line)

    def state(self):
        mem = self.e.mem
        crc = 0
        for p in self.projects:
            for sdef, objs in p.screens:
                if sdef is not None:
                    crc = zlib.crc32(bytes(mem[sdef + 8:sdef + 32]), crc)
                for a, n in objs:
                    crc = zlib.crc32(bytes(mem[a + 8:a + 44]), crc)
                    if mem[a + 40] == 1 and n >= 100:
                        crc = zlib.crc32(bytes(mem[a + 48:a + 100]), crc)
                        k = self.text_len(a)
                        crc = zlib.crc32(bytes(mem[a + 100:a + 100 + k]),
                                         crc)
                    else:
                        crc = zlib.crc32(bytes(mem[a + 48:a + n]), crc)
        self.emit("  crc %08x" % (crc & M32))

    def order(self):
        g = self.e.u32
        p = g(PROJ_HEAD)
        while p != PROJ_HEAD:
            pn = self.proj_at[p]
            idx = []
            head = p + 12
            sc = g(head)
            while sc != head:
                idx.append(str(self.screen_at[sc][1]))
                sc = g(sc)
            self.emit("  project %d:%s" % (pn, "".join(" " + i
                                                       for i in idx)))
            p = g(p)

    # ---- calls

    def string(self, s, off=0):
        a = self.scratch + off
        self.e.write(a, s.encode("latin-1") + b"\0")
        return a

    def call(self, addr, kinds, result, args):
        """args are the script's fields after the name; returns what is
        printed for the result."""
        e = self.e
        regs = []
        fi = 12
        sbuf = 0
        outp = None
        ai = 0
        for k in kinds:
            if k == "o":
                regs.append(self.cur)
            elif k == "h":
                regs.append(int(args[ai], 0))
                regs.append(int(args[ai + 1], 0))
                ai += 2
            elif k == "i":
                regs.append(int(args[ai], 0))
                ai += 1
            elif k == "s":
                regs.append(self.string(args[ai], 256 + 256 * sbuf))
                sbuf += 1
                ai += 1
            elif k == "f":
                e.fpr[fi] = int(args[ai], 0) & M32
                fi += 1
                ai += 1
            elif k == "v":
                a = self.scratch + 2048
                for j in range(4):
                    e.put32(a + 4 * j, int(args[ai + j], 0) & M32)
                regs.append(a)
                ai += 4
            elif k == "b":
                outp = self.scratch + 2560
                for j, v in enumerate((7, -9, 11, -13)):
                    e.put32(outp + 4 * j, v & M32)
                regs += [outp + 4 * j for j in range(4)]
            elif k in "pq":
                outp = self.scratch + 2560
                if k == "p":
                    e.put32(outp, fbits(1.25))
                    e.put32(outp + 4, fbits(-3.5))
                else:
                    e.put32(outp, 7)
                    e.put32(outp + 4, (-9) & M32)
                regs += [outp, outp + 4]
        v = e.call(addr, *[s32(r & M32) for r in regs], limit=2000000)
        if result == "I":
            return "  = %d" % s32(v)
        if result == "F":
            return "  = %08x" % (e.fpr[0] & M32)
        if result == "P":
            return "  = %08x %08x" % (e.u32(outp), e.u32(outp + 4))
        if result == "Q":
            return "  = %d %d" % (s32(e.u32(outp)), s32(e.u32(outp + 4)))
        if result == "B":
            return "  = %d %d %d %d" % tuple(s32(e.u32(outp + 4 * j))
                                              for j in range(4))
        return None

    def load(self, path):
        e = self.e
        d = Path(path).read_bytes()
        off, size = flailer_chunk(d)
        base = e.alloc(8 + size, align=16)
        e.write(base, d[off:off + 8 + size])
        p = Project(len(self.projects), e.mem, base, size)
        self.projects.append(p)
        self.proj_at[p.proj] = p.n
        for i, (sdef, objs) in enumerate(p.screens):
            if sdef is not None:
                self.screen_at[sdef] = (p.n, i)
        self.size_of = getattr(self, "size_of", {})
        for i, (a, n) in enumerate(p.objects):
            self.obj_at[a] = "%d:%d" % (p.n, i)
            self.size_of[a] = n
        v = e.call(F_LOADER, base, limit=5000000)
        self.emit("  loaded %d" % v)

    def op(self, a):
        e = self.e
        o = a[0]
        if o == "load":
            self.load(a[1])
        elif o == "screen":
            v = e.call(F_SCREEN, s32(int(a[1], 0)), limit=100000) & M32
            if v:
                pn, i = self.screen_at[v]
                self.emit("  screen %d:%d" % (pn, i))
            else:
                self.emit("  screen none")
        elif o == "find":
            self.cur = e.call(F_OBJECT, s32(int(a[1], 0)),
                              s32(int(a[2], 0)), int(a[3], 0),
                              limit=200000) & M32
            self.emit("  found %s" % self.name(self.cur))
        elif o == "group":
            after = self.cur if int(a[4], 0) else 0
            self.cur = e.call(F_GROUP, s32(int(a[1], 0)), s32(int(a[2], 0)),
                              int(a[3], 0), after, limit=200000) & M32
            self.emit("  found %s" % self.name(self.cur))
        elif o == "order":
            self.order()
        elif o == "state":
            self.state()
        elif o == "poke":
            if self.cur == 0:
                self.emit("  no object")
                return
            e.write(self.cur + int(a[1], 0),
                    struct.pack("<I", int(a[2], 0) & M32))
            self.dump("cur", self.cur)
        elif o == "m":
            if self.cur == 0:
                self.emit("  no object")
                return
            addr, kinds, result = METHODS[a[1]]
            r = self.call(addr, kinds, result, a[2:])
            if r:
                self.emit(r)
            self.dump("cur", self.cur)
        elif o == "w":
            addr, kinds, result = WRAPPERS[a[1]]
            r = self.call(addr, kinds, result, a[2:])
            if r:
                self.emit(r)
            obj = e.call(F_OBJECT, s32(int(a[2], 0)), s32(int(a[3], 0)), 0,
                         limit=200000) & M32
            self.dump("obj", obj)
        else:
            raise ValueError(o)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="flailer_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return pcc.HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


diff = pcc.diff


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return sc


# ============================================================= mutations

F = FLAILER
MUTATIONS = [
    # The registry and the loader's pass.
    ("project-at-head", F, "    sList[sNumProjects] = sNumProjects;",
     "    memmove(&sList[1], &sList[0], (size_t)sNumProjects * sizeof(int));"
     + NL + "    sList[0] = sNumProjects;"),
    ("loader-visible", F, "screen_chunk(s)->Visible = 1;",
     "screen_chunk(s)->Visible = 0;"),
    ("loader-no-language", F,
     "            if (o->ObjectType == FLAILER_TYPE_TEXT)" + NL
     + "                flailertext_update_language_text(",
     "            if (0)" + NL + "                flailertext_update_language_text("),

    # FindFlailerScreen's move to the front.
    ("skip-one", F, "if (skipped >= 2) {", "if (skipped >= 1) {"),
    ("skip-three", F, "if (skipped >= 2) {", "if (skipped >= 3) {"),
    ("skip-per-project", F,
     "        FlailerProject *p = &sProjects[sList[n]];",
     "        FlailerProject *p = &sProjects[sList[n]];" + NL
     + "        skipped = 0;"),
    ("screen-stays", F,
     "                memmove(&p->order[1], &p->order[0], i * sizeof(uint32_t));"
     + NL + "                p->order[0] = idx;",
     "                (void)idx;"),
    ("project-stays", F,
     "                memmove(&sList[1], &sList[0], (size_t)n * sizeof(int));"
     + NL + "                sList[0] = proj;",
     "                (void)proj;"),

    # The object searches.
    ("find-any-type", F,
     "        if (o->NameHash != object) continue;" + NL
     + "        if (type == FLAILER_TYPE_ANY || o->ObjectType == type) return o;",
     "        if (o->NameHash != object) continue;" + NL + "        return o;"),
    ("find-first-name", F,
     "        if (o->NameHash != object) continue;" + NL
     + "        if (type == FLAILER_TYPE_ANY || o->ObjectType == type) return o;",
     "        if (o->NameHash != object) continue;" + NL
     + "        return (type == FLAILER_TYPE_ANY || o->ObjectType == type)"
     + " ? o : NULL;"),
    ("group-any-type", F,
     "        if (o->GroupHash != group) continue;" + NL
     + "        if (type == FLAILER_TYPE_ANY || o->ObjectType == type) return o;",
     "        if (o->GroupHash != group) continue;" + NL + "        return o;"),
    ("group-after-same", F,
     "        if (i == s->count) return NULL;" + NL + "        i++;",
     "        if (i == s->count) return NULL;"),
    ("group-after-restart", F,
     "        if (i == s->count) return NULL;",
     "        if (i == s->count) i = (uint32_t)-1;"),

    # FlailerObjectChunk.
    ("object-alpha-corner", F,
     "return flailerbitmap_get_alpha(BITMAP(o), 0);",
     "return flailerbitmap_get_alpha(BITMAP(o), 3);"),
    ("z-same-dirty", F, "    if (o->Z == z) return;" + NL, ""),
    ("z-dirty", F, "o->DirtyFlag = 2;", "o->DirtyFlag = 3;"),
    ("width-round", F,
     "return ee_trunc_w(flailerobject_get_width_float(o));",
     "return ee_trunc_w(flailerobject_get_width_float(o) + 0.5f);"),
    ("height-round", F,
     "return ee_trunc_w(flailerobject_get_height_float(o));",
     "return ee_trunc_w(flailerobject_get_height_float(o) + 0.5f);"),
    ("object-alpha-one-corner", F,
     "        flailerbitmap_set_alpha(BITMAP(o), a, FLAILER_ALL_CORNERS);"
     + NL + "}",
     "        flailerbitmap_set_alpha(BITMAP(o), a, 0);" + NL + "}"),
    ("rotation-text", F,
     "    if (o->ObjectType == FLAILER_TYPE_BITMAP)" + NL
     + "        flailerbitmap_set_rotation(BITMAP(o), r);",
     "    o->Rotation = ee_trunc_w(r);" + NL
     + "    if (o->ObjectType == FLAILER_TYPE_BITMAP)" + NL
     + "        flailerbitmap_set_rotation(BITMAP(o), r);"),
    ("visibility-bool", F,
     "    o->Visibility = (int8_t)v;" + NL + "    if (v",
     "    o->Visibility = (int8_t)(v != 0);" + NL + "    if (v"),
    ("scale-x-same-dirty", F, "    if (o->ScaleX == sx) return;" + NL, ""),
    ("scale-x-dirty", F,
     "    o->ScaleX = sx;" + NL + "    o->DirtyFlag = 3;",
     "    o->ScaleX = sx;" + NL + "    o->DirtyFlag = 4;"),
    ("scale-y-dirty", F,
     "    o->ScaleY = sy;" + NL + "    o->DirtyFlag = 3;",
     "    o->ScaleY = sy;" + NL + "    o->DirtyFlag = 4;"),
    ("center-y-height", F, "    *y = t + halfW;",
     "    *y = t + flailerobject_get_height_float(o) * 0.5f;"),
    ("center-x-full", F, "    *x = l + halfW;",
     "    *x = l + halfW * 2.0f;"),
    ("set-center-x-height", F,
     "o, x - flailerobject_get_width_float(o) * 0.5f);",
     "o, x - flailerobject_get_height_float(o) * 0.5f);"),
    ("set-center-y-width", F,
     "o, y - flailerobject_get_height_float(o) * 0.5f);",
     "o, y - flailerobject_get_width_float(o) * 0.5f);"),
    ("right-wins", F,
     "        if (f & BUI_FMT_CENTER)     *x = o->X - w * 0.5f;" + NL
     + "        else if (f & BUI_FMT_RIGHT) *x = o->X - w;",
     "        if (f & BUI_FMT_RIGHT)       *x = o->X - w;" + NL
     + "        else if (f & BUI_FMT_CENTER) *x = o->X - w * 0.5f;"),
    ("bitmap-aligned", F,
     "    } else {" + NL + "        *x = o->X;" + NL + "    }",
     "    } else {" + NL + "        *x = o->X - flailerobject_get_width_float(o)"
     " * 0.5f;" + NL + "    }"),
    ("x-same-dirty", F, "    if (o->X == x) return;" + NL, ""),
    ("pos-dirty", F,
     "    o->X = x;" + NL + "    o->DirtyFlag = 4;",
     "    o->X = x;" + NL + "    o->DirtyFlag = 5;"),
    ("y-dirty", F,
     "    o->Y = y;" + NL + "    o->DirtyFlag = 4;",
     "    o->Y = y;" + NL + "    o->DirtyFlag = 3;"),
    ("clip-same", F, "    if (o->ClipToPoly == poly) return;" + NL, ""),
    ("clip-dirty", F,
     "    o->DirtyFlag = 4;" + NL + "    o->ClipToPoly = poly;",
     "    o->DirtyFlag = 3;" + NL + "    o->ClipToPoly = poly;"),
    ("clip-no-format", F,
     "    if (o->ObjectType == FLAILER_TYPE_TEXT)" + NL
     + "        flailertext_set_format_options(TEXT(o), BUI_FMT_CLIP);",
     "    (void)0;"),

    # FlailerTextChunk.
    ("format-dirty", F,
     "    t->Object.DirtyFlag = 5;" + NL + "    t->FormatOptions |= f;",
     "    t->Object.DirtyFlag = 4;" + NL + "    t->FormatOptions |= f;"),
    ("clear-toggles", F, "t->FormatOptions &= ~f;", "t->FormatOptions ^= f;"),
    ("color-alpha-taken", F,
     "(t->Color & 0xff000000u) | (c & 0x00ffffffu);", "c;"),
    ("color-same-dirty", F,
     "    if (v == t->Color) return;" + NL + "    t->Color = v;" + NL
     + "    t->Object.DirtyFlag = 7;",
     "    t->Color = v;" + NL + "    t->Object.DirtyFlag = 7;"),
    ("color-dirty", F, "t->Object.DirtyFlag = 7;", "t->Object.DirtyFlag = 6;"),
    ("string-same-set", F,
     "    if (strcmp(s, t->String) == 0) return;" + NL, ""),
    ("string-uncut", F,
     "    if (t->MaxChars > 0) t->String[t->MaxChars - 1] = 0;" + NL, ""),
    ("string-keeps-language", F, "    t->LanguageID = 0;" + NL, ""),
    ("language-same-set", F, "    if (t->LanguageID == id) return;" + NL, ""),
    ("language-keeps-string", F, "    t->String[0] = 0;" + NL, ""),
    ("text-alpha-mask", F,
     "(t->Color & 0x00ffffffu) | ((uint32_t)a << 24);",
     "(t->Color & 0x00ffffffu) | ((uint32_t)(a & 0x7f) << 24);"),
    ("text-alpha-dirty", F, "t->Object.DirtyFlag = 6;",
     "t->Object.DirtyFlag = 7;"),
    ("text-alpha-signed", F, "return (int32_t)(t->Color >> 24);",
     "return (int32_t)t->Color >> 24;"),
    ("text-vector-bgr", F,
     "flailertext_set_color(t, r | g << 8 | b << 16);",
     "flailertext_set_color(t, b | g << 8 | r << 16);"),
    ("text-vector-alpha-first", F,
     "    flailertext_set_color(t, r | g << 8 | b << 16);" + NL
     + "    flailertext_set_alpha(t, a);",
     "    flailertext_set_alpha(t, a);" + NL
     + "    flailertext_set_color(t, r | g << 8 | b << 16);"),
    ("text-vector-round", F,
     "    uint32_t r = (uint32_t)ee_trunc_w(c->x);" + NL
     + "    uint32_t g = (uint32_t)ee_trunc_w(c->y);" + NL
     + "    uint32_t b = (uint32_t)ee_trunc_w(c->z);",
     "    uint32_t r = (uint32_t)ee_trunc_w(c->x + 0.5f);" + NL
     + "    uint32_t g = (uint32_t)ee_trunc_w(c->y);" + NL
     + "    uint32_t b = (uint32_t)ee_trunc_w(c->z);"),

    # FlailerBitmapChunk.
    ("bitmap-alpha-dirty", F, "    b->Object.DirtyFlag = 6;",
     "    b->Object.DirtyFlag = 7;"),
    ("bitmap-alpha-all-mask", F,
     "b->Colors[i] = (b->Colors[i] & 0x00ffffffu) | top;",
     "b->Colors[i] = top;"),
    ("bitmap-alpha-corner-0", F,
     "b->Colors[corner] = (b->Colors[corner] & 0x00ffffffu) | top;",
     "b->Colors[0] = (b->Colors[0] & 0x00ffffffu) | top;"),
    ("bitmap-rotation-same", F,
     "    if (b->Object.Rotation == v) return;" + NL, ""),
    ("bitmap-rotation-round", F, "int32_t v = ee_trunc_w(r);",
     "int32_t v = ee_trunc_w(r + 0.5f);"),
    ("bitmap-rotation-dirty", F, "b->Object.DirtyFlag = 9;",
     "b->Object.DirtyFlag = 8;"),
    ("bitmap-color-asks-last", F, "if (b->Colors[0] != c)",
     "if (b->Colors[3] != c)"),
    ("bitmap-color-dirty", F, "b->Object.DirtyFlag = 7;",
     "b->Object.DirtyFlag = 6;"),
    ("bitmap-color-three", F, "    b->Colors[3] = c;" + NL, ""),
    ("bitmap-vector-alpha-first", F,
     "    flailerbitmap_set_color(b, r | g << 8 | bl << 16);" + NL
     + "    flailerbitmap_set_alpha(b, a, FLAILER_ALL_CORNERS);",
     "    flailerbitmap_set_alpha(b, a, FLAILER_ALL_CORNERS);" + NL
     + "    flailerbitmap_set_color(b, r | g << 8 | bl << 16);"),
    ("bitmap-vector-bgr", F,
     "flailerbitmap_set_color(b, r | g << 8 | bl << 16);",
     "flailerbitmap_set_color(b, bl | g << 8 | r << 16);"),
    ("texture-keeps-info", F, "    b->pTextureInfo = 0;" + NL, ""),
    ("texture-dirty", F, "b->Object.DirtyFlag = 10;",
     "b->Object.DirtyFlag = 9;"),
    ("bitmap-get-alpha-0", F,
     "return (int32_t)(b->Colors[corner] >> 24);",
     "return (int32_t)(b->Colors[0] >> 24);"),

    # The wrappers.
    ("printf-any-type", F,
     "        flailer_find_object(screen, object, FLAILER_TYPE_TEXT);" + NL
     + "    va_list ap;",
     "        flailer_find_object(screen, object, FLAILER_TYPE_ANY);" + NL
     + "    va_list ap;"),
    ("printf-shared-buffer", F,
     "n = vsnprintf(sPrintfChunkBuffer, sizeof(sPrintfChunkBuffer), fmt, ap);",
     "n = vsnprintf(sPrintfBuffer, sizeof(sPrintfBuffer), fmt, ap);"),
    ("printf-missing-count", F,
     "    if (o == NULL) return 0;" + NL + "    va_start(ap, fmt);",
     "    if (o == NULL) return -1;" + NL + "    va_start(ap, fmt);"),
    ("text-color-any-type", F,
     "        flailer_find_object(screen, object, FLAILER_TYPE_TEXT);" + NL
     + "    if (o) flailertext_set_color(TEXT(o), c);",
     "        flailer_find_object(screen, object, FLAILER_TYPE_ANY);" + NL
     + "    if (o) flailertext_set_color(TEXT(o), c);"),
    ("top-left-missing-kept", F,
     "    *y = 0.0f;" + NL + "    *x = 0.0f;", "    (void)0;"),
    ("top-left-int-round", F, "    *x = ee_trunc_w(fx);",
     "    *x = ee_trunc_w(fx + 0.5f);"),
    ("scale-missing-zeroed", F,
     "    if (o == NULL) return;" + NL + "    *sx = o->ScaleX;",
     "    if (o == NULL) { *sx = 0.0f; *sy = 0.0f; return; }" + NL
     + "    *sx = o->ScaleX;"),
    ("set-center-float", F,
     "flailerobject_set_top_left_x(o, (float)x - (float)w * 0.5f);",
     "flailerobject_set_top_left_x(o, (float)x"
     " - flailerobject_get_width_float(o) * 0.5f);"),
    ("language-any-type", F,
     "        flailer_find_object(screen, object, FLAILER_TYPE_TEXT);" + NL
     + "    if (o) flailertext_set_language_id(TEXT(o), id);",
     "        flailer_find_object(screen, object, FLAILER_TYPE_ANY);" + NL
     + "    if (o) flailertext_set_language_id(TEXT(o), id);"),
    ("texture-any-type", F,
     "        flailer_find_object(screen, object, FLAILER_TYPE_BITMAP);" + NL
     + "    if (o) flailerbitmap_change_texture",
     "        flailer_find_object(screen, object, FLAILER_TYPE_ANY);" + NL
     + "    if (o) flailerbitmap_change_texture"),
    ("visibility-deletes-always", F,
     "    if (v == FLAILER_OBJECT_INVISIBLE) flailerobject_delete_strip(o);",
     "    flailerobject_delete_strip(o);"),
    ("strip-kept", F, "    o->pFlailerStrip = 0;" + NL, ""),
    ("group-visibility-value", F,
     "        o->Visibility = (int8_t)v;" + NL + "}",
     "        o->Visibility = (int8_t)(v & 1);" + NL + "}"),
    ("group-no-discarded-search", F,
     "    (void)flailer_find_object_by_group(screen, group, FLAILER_TYPE_ANY, NULL);"
     + NL, ""),
    # SetWidth, SetHeight and ScaleAboutCenter.
    ("set-width-height", F, "flailerobject_set_scale_x(o, w / (float)tw);",
     "flailerobject_set_scale_x(o, w / (float)th);"),
    ("set-height-no-test", F, "    flailerobject_set_scale_y(o, h / (float)th);",
     "    o->ScaleY = h / (float)th;"),
    ("sac-text-dirty", F,
     "    o->DirtyFlag = 3;" + NL + "    hw = ",
     "    o->DirtyFlag = 4;" + NL + "    hw = "),
    ("sac-text-half", F,
     "hw = flailerobject_get_width_float(o) / (o->ScaleX + o->ScaleX);",
     "hw = flailerobject_get_width_float(o) / o->ScaleX;"),
    ("sac-text-hh-scalex", F,
     "hh = flailerobject_get_height_float(o) / (o->ScaleY + o->ScaleY);",
     "hh = flailerobject_get_height_float(o) / (o->ScaleX + o->ScaleX);"),
    ("sac-text-left-x-back", F,
     "        o->X = o->X + hw * (o->ScaleX - s);",
     "        o->X = o->X - hw * (o->ScaleX - s);"),
    ("sac-text-center-moves-x", F,
     "    } else if (f & BUI_FMT_CENTER) {" + NL
     + "        o->Y = o->Y + hh * (o->ScaleY - s);",
     "    } else if (f & BUI_FMT_CENTER) {" + NL
     + "        o->X = o->X + hw * (o->ScaleX - s);" + NL
     + "        o->Y = o->Y + hh * (o->ScaleY - s);"),
    ("sac-text-right-scaley", F,
     "        o->Y = o->Y + hh * (o->ScaleX - s);",
     "        o->Y = o->Y + hh * (o->ScaleY - s);"),
    ("sac-text-center-first", F, "    if (f & BUI_FMT_LEFT) {",
     "    if ((f & BUI_FMT_LEFT) && !(f & BUI_FMT_CENTER)) {"),
    ("sac-text-none-as-left", F, "    if (f & BUI_FMT_LEFT) {",
     "    if ((f & BUI_FMT_LEFT) || !(f & 7)) {"),
    ("sac-text-scale-x-only", F,
     "    o->ScaleY = s;" + NL + "    o->ScaleX = s;" + NL + "}" + NL + NL
     + "// The bitmap's",
     "    o->ScaleX = s;" + NL + "}" + NL + NL + "// The bitmap's"),
    ("sac-bitmap-dirty", F,
     "    o->DirtyFlag = 3;" + NL + "    texture_size(b, &tw, &th);",
     "    o->DirtyFlag = 4;" + NL + "    texture_size(b, &tw, &th);"),
    ("sac-bitmap-width-for-height", F,
     "dy = (float)th * 0.5f * (o->ScaleY - s);",
     "dy = (float)tw * 0.5f * (o->ScaleY - s);"),
    ("sac-bitmap-back", F, "    o->X = o->X + dx;", "    o->X = o->X - dx;"),
    ("bitmap-width-truncated", F,
     "    return (float)w * b->Object.ScaleX;",
     "    return (float)(int32_t)((float)w * b->Object.ScaleX);"),

    # The bounding box and the centres.
    ("bbox-width-up", F, "    *right  = x + w;", "    *right  = x + w + 1;"),
    ("bbox-height-from-width", F, "    *bottom = y + h;", "    *bottom = y + w;"),
    ("center-rounds-up", F, "    *y = t + (b - t) / 2;",
     "    *y = t + (b - t + 1) / 2;"),
    ("center-x-width", F,
     "o, (float)x - (float)flailerobject_get_height(o) * 0.5f);",
     "o, (float)x - (float)flailerobject_get_width(o) * 0.5f);"),
    ("center-y-float", F,
     "o, (float)y - (float)flailerobject_get_height(o) * 0.5f);",
     "o, (float)y - flailerobject_get_height_float(o) * 0.5f);"),

    # The group walks.
    ("group-position-anchor-x", F, "    dy = y - a->Y;", "    dy = y - a->X;"),
    ("group-position-everyone", F,
     "        if (o->GroupHash != group) continue;" + NL
     + "        flailerobject_set_top_left_x(o, o->X + dx);",
     "        flailerobject_set_top_left_x(o, o->X + dx);"),
    ("group-offset-dx-twice", F,
     "flailerobject_set_top_left_y(o, o->Y + (float)dy);",
     "flailerobject_set_top_left_y(o, o->Y + (float)dx);"),
    ("group-poly-everyone", F,
     "if (o->GroupHash == group) o->RenderOnPoly = poly;",
     "o->RenderOnPoly = poly;"),
    ("group-alpha-first-only", F,
     "         o = flailer_find_object_by_group(screen, group, FLAILER_TYPE_ANY, o))"
     + NL + "        flailerobject_set_alpha(o, a);",
     "         o = NULL)" + NL + "        flailerobject_set_alpha(o, a);"),

    # MakeVerticalLine.
    ("vline-no-swap", F, "    if (y2 < y1) {", "    if (0) {"),
    ("vline-scaled-unit", F,
     "unit = flailerbitmap_height_float(BITMAP(o)) / o->ScaleY;",
     "unit = flailerbitmap_height_float(BITMAP(o));"),
    ("vline-any-type", F,
     "        flailer_find_object(screen, object, FLAILER_TYPE_BITMAP);" + NL
     + "    float unit",
     "        flailer_find_object(screen, object, FLAILER_TYPE_ANY);" + NL
     + "    float unit"),
    ("vline-between-gap", F, "                                   + 4.0f,",
     "                                   + 3.0f,"),
    ("vline-between-top-only", F,
     "(a->Y + flailerobject_get_height_float(a))", "(a->Y)"),
]

EQUIVALENT = {
    # A search made right after another for the same screen finds it at the
    # head of the head project, having passed nothing, and moves nothing;
    # so the second search leaves the same order the first did.
    # Retail walks on from after->Next until it meets the screen's list
    # head; an `after` from another screen walks that screen's circular
    # list and never meets it. Every caller passes the object the last
    # call returned, so the case is not one the script can put to retail.
    "group-after-restart":
        "an `after` from another screen hangs retail; no caller makes one",
    "group-no-discarded-search":
        "the loop's own first search finds the screen where the discarded "
        "one left it, at the head, and moves nothing",
    # pFlailerStrip is 0 in every object on the disc and only the renderer
    # sets it, which neither side runs: there is never a strip to let go.
    "visibility-deletes-always":
        "no object has a strip -- 0 on the disc, and nothing here builds one",
    "strip-kept":
        "no object has a strip -- 0 on the disc, and nothing here builds one",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base = model(lines)
    caught, survived, missing, equivalent = 0, [], [], []
    indir = tempfile.TemporaryDirectory()
    scp = write_script(indir.name, lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-44s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    indir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        print("  listed as equivalent but %s: %s"
              % ("caught" if name in ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

    lines = script()
    got = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
